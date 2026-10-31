from __future__ import annotations
import io
import logging
import re
from pathlib import Path
from typing import Any
import pymupdf as fitz
import pandas as pd
import numpy as np
import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, UnidentifiedImageError
from app.core.config import settings

logger = logging.getLogger(__name__)
MAX_IMAGE_PIXELS = settings.max_image_pixels
SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".xlsx", ".xls", ".csv"}

class DocumentProcessingError(Exception):
    """Expected document-processing error safe to persist in job status."""
def _estimate_skew_angle(image: Image.Image) -> float:
    """Estimate a small text rotation using horizontal projection profiles."""
    sample = ImageOps.grayscale(image).copy()
    sample.thumbnail((1200, 1200), Image.Resampling.LANCZOS)

    if sample.width < 150 or sample.height < 150:
        return 0.0

    pixels = np.asarray(sample)

    if np.count_nonzero(pixels < 180) < 100:
        return 0.0

    def projection_score(angle: float) -> float:
        rotated = sample.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=255,
        )
        ink = np.asarray(rotated) < 180
        row_projection = ink.sum(axis=1).astype(np.float64)
        return float(np.var(row_projection))

    baseline_score = projection_score(0.0)
    best_angle = 0.0
    best_score = baseline_score

    # Search a conservative range of small rotations.
    for angle in np.arange(-3.0, 3.01, 0.5):
        score = projection_score(float(angle))
        if score > best_score:
            best_score = score
            best_angle = float(angle)

    # Refine the best coarse estimate.
    for angle in np.arange(best_angle - 0.5, best_angle + 0.51, 0.1):
        score = projection_score(float(angle))
        if score > best_score:
            best_score = score
            best_angle = float(angle)

    improvement = (best_score - baseline_score) / max(baseline_score, 1.0)

    # Avoid rotating already-horizontal or insufficiently confident text.
    if abs(best_angle) < 0.25 or improvement < 0.01:
        return 0.0

    return round(best_angle, 2)
def _adaptive_binarize(image: Image.Image) -> Image.Image:
    """Apply local adaptive thresholding for faint or unevenly lit scans."""
    gray = image.convert("L")

    # Suppress isolated noise while preserving most character strokes.
    denoised = gray.filter(ImageFilter.MedianFilter(size=3))

    pixels = np.asarray(denoised, dtype=np.int16)
    local_mean = np.asarray(
        denoised.filter(ImageFilter.BoxBlur(25)),
        dtype=np.int16,
    )

    # Use a stronger offset to prevent background noise becoming foreground.
    threshold = local_mean - 20

    binary = np.where(
        pixels < threshold,
        0,
        255,
    ).astype(np.uint8)

    return Image.fromarray(binary)


def _run_tesseract_ocr(
    image: Image.Image,
) -> tuple[str, float | None]:
    """Extract text and mean confidence from a prepared OCR image."""
    data = pytesseract.image_to_data(
        image,
        config="--oem 3 --psm 6",
        output_type=pytesseract.Output.DICT,
        timeout=settings.ocr_timeout_seconds,
    )

    grouped: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    count = len(data.get("text", []))

    for index in range(count):
        token = str(data["text"][index]).strip()
        if not token:
            continue

        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        grouped.setdefault(key, []).append(token)

        try:
            confidence = float(data["conf"][index])
            if confidence >= 0:
                confidences.append(confidence)
        except (ValueError, TypeError):
            pass

    line_text = [
        " ".join(tokens)
        for _, tokens in sorted(grouped.items())
    ]
    text = "\n".join(line_text)
    mean_confidence = (
        sum(confidences) / len(confidences)
        if confidences
        else None
    )

    return text, mean_confidence
def _ocr_image_detailed(image: Image.Image) -> tuple[str, float | None]:
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise DocumentProcessingError(f"Image exceeds the {MAX_IMAGE_PIXELS:,}-pixel processing limit")
    image = ImageOps.exif_transpose(image).convert("RGB")

    # Preserve the original grayscale detail for reliable OCR.
    # Enhancement and upscaling are avoided because they can amplify scan noise.
    gray = ImageOps.grayscale(image)
    # Correct 90/180/270-degree scans when Tesseract OSD has a confident orientation.
    try:
        osd = pytesseract.image_to_osd(gray, timeout=min(settings.ocr_timeout_seconds, 5.0))
        rotate_match = re.search(r"(?m)^Rotate:\s*(0|90|180|270)\s*$", osd)
        confidence_match = re.search(r"(?m)^Orientation confidence:\s*([0-9.]+)", osd)
        rotation = int(rotate_match.group(1)) if rotate_match else 0
        confidence = float(confidence_match.group(1)) if confidence_match else 0.0
        if rotation and confidence >= 3.0:
            gray = gray.rotate(360 - rotation, expand=True)
    except Exception:
        # OSD can fail on short/low-quality text. Continue without changing pixels.
        pass
    try:
        # Correct small text rotation before OCR.
        skew_angle = _estimate_skew_angle(gray)
        if skew_angle:
            gray = gray.rotate(
                skew_angle,
                resample=Image.Resampling.BICUBIC,
                expand=False,
                fillcolor=255,
            )

        text, mean_confidence = _run_tesseract_ocr(gray)

        # Retry with adaptive binarization when the initial OCR result is weak.
        if not text or mean_confidence is None or mean_confidence < 60:
            try:
                adaptive_image = _adaptive_binarize(gray)
                fallback_text, fallback_confidence = _run_tesseract_ocr(
                    adaptive_image
                )

                if fallback_text and (
                    not text
                    or (
                        fallback_confidence is not None
                        and (
                            mean_confidence is None
                            or fallback_confidence > mean_confidence
                        )
                    )
                ):
                    text = fallback_text
                    mean_confidence = fallback_confidence

            except Exception:
                # Keep the original OCR result if the fallback fails.
                pass

        return text, mean_confidence
    except pytesseract.TesseractNotFoundError as exc:
        raise DocumentProcessingError(
            "Tesseract OCR is not installed or is not on PATH"
        ) from exc
    except Exception as exc:
        raise DocumentProcessingError(
            f"OCR failed: {type(exc).__name__}"
        ) from exc
    except pytesseract.TesseractNotFoundError as exc:
        raise DocumentProcessingError("Tesseract OCR is not installed or is not on PATH") from exc
    except Exception as exc:
        raise DocumentProcessingError(f"OCR failed: {type(exc).__name__}") from exc


def _ocr_image(image: Image.Image) -> str:
    return _ocr_image_detailed(image)[0]


def process_pdf(path: Path) -> tuple[str, int, dict[str, Any]]:
    parts: list[str] = []
    ocr_confidences: list[float] = []
    try:
        with fitz.open(path) as pdf:
            page_count = len(pdf)
            if page_count == 0:
                raise DocumentProcessingError("PDF has no pages")
            if page_count > settings.max_pdf_pages:
                raise DocumentProcessingError(f"PDF has {page_count} pages; configured limit is {settings.max_pdf_pages}")
            for index, page in enumerate(pdf):
                text = page.get_text("text").strip()
                has_raster_images = bool(page.get_images(full=True))
                if len(text) < 80 or (has_raster_images and len(text) < 200):
                    if page.rect.width * page.rect.height * 4 > MAX_IMAGE_PIXELS:
                        raise DocumentProcessingError(f"PDF page {index + 1} exceeds the OCR rendering pixel limit")
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr_text, confidence = _ocr_image_detailed(image)
                    if confidence is not None:
                        ocr_confidences.append(confidence)
                    if ocr_text:
                        text = (text + "\n" + ocr_text).strip()
                parts.append(f"[PAGE {index + 1}]\n{text}")
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError(f"PDF could not be read: {type(exc).__name__}") from exc
    mean_confidence = sum(ocr_confidences) / len(ocr_confidences) if ocr_confidences else None
    return "\n\n".join(parts), page_count, {
        "kind": "pdf", "ocr_mean_confidence": mean_confidence,
        "low_ocr_confidence": mean_confidence is not None and mean_confidence < 60,
    }


def process_image(path: Path) -> tuple[str, int, dict[str, Any]]:
    texts: list[str] = []
    confidences: list[float] = []
    try:
        with Image.open(path) as image:
            frame_count = getattr(image, "n_frames", 1)
            if frame_count > settings.max_pdf_pages:
                raise DocumentProcessingError(f"Image contains {frame_count} frames; configured limit is {settings.max_pdf_pages}")
            for frame in range(frame_count):
                image.seek(frame)
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise DocumentProcessingError(f"Image frame exceeds the {MAX_IMAGE_PIXELS:,}-pixel processing limit")
                text, confidence = _ocr_image_detailed(image.copy())
                texts.append(f"[FRAME {frame + 1}]\n{text.strip()}")
                if confidence is not None:
                    confidences.append(confidence)
    except DocumentProcessingError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DocumentProcessingError("Image is corrupted or is not a supported image") from exc
    except Exception as exc:
        raise DocumentProcessingError(f"Image OCR failed: {type(exc).__name__}") from exc
    mean_confidence = sum(confidences) / len(confidences) if confidences else None
    return "\n\n".join(texts), len(texts), {
        "kind": "image", "ocr_mean_confidence": mean_confidence,
        "low_ocr_confidence": mean_confidence is not None and mean_confidence < 60,
    }

def _spreadsheet_to_text(sheet_name: str, frame: pd.DataFrame) -> str:
    """Represent rows as labeled key/value pairs so rule extraction can read tabular invoices."""
    headers = [str(column).strip() for column in frame.columns]
    normalized = [re.sub(r"[^a-z0-9]+", " ", header.casefold()).strip() for header in headers]
    parts = [f"[SHEET {sheet_name}]"]
    description_idx = next((i for i, name in enumerate(normalized) if any(word in name for word in ("description", "item description", "product name", "item name"))), None)
    quantity_idx = next((i for i, name in enumerate(normalized) if name in {"qty", "quantity", "units"}), None)
    price_idx = next((i for i, name in enumerate(normalized) if name in {"unit price", "price per unit", "rate", "unit cost"}), None)
    amount_idx = next((i for i, name in enumerate(normalized) if name in {"amount", "line total", "line amount", "total amount", "extended price"}), None)
    # Only recognize a line-item table when there is a description and at least an amount column.
    line_table = description_idx is not None and amount_idx is not None
    for row_index, row in enumerate(frame.itertuples(index=False, name=None), start=1):
        clean_values = ["" if pd.isna(value) else str(value).strip() for value in row]
        pairs = [f"{headers[i].replace('_', ' ')}: {value}" for i, value in enumerate(clean_values) if value]
        if pairs:
            parts.append(f"[ROW {row_index}]\n" + "\n".join(pairs))
        if line_table:
            # Use a normalized extra line the local parser can recognize. Header row is already columns.
            description = clean_values[description_idx] if description_idx < len(clean_values) else ""
            amount = clean_values[amount_idx] if amount_idx < len(clean_values) else ""
            quantity = clean_values[quantity_idx] if quantity_idx is not None and quantity_idx < len(clean_values) else ""
            price = clean_values[price_idx] if price_idx is not None and price_idx < len(clean_values) else ""
            if description and amount:
                parts.append(f"Line Item: {description} | Quantity: {quantity or 'null'} | Unit Price: {price or 'null'} | Amount: {amount}")
    return "\n".join(parts)


_KEY_VALUE_LABELS = {
    "invoice number", "invoice no", "invoice date", "bill number", "bill date",
    "supplier", "supplier name", "vendor", "vendor name", "customer", "customer name",
    "bill to", "subtotal", "sub total", "tax", "vat", "gst", "total", "currency",
}

def _key_value_frame_to_text(sheet_name: str, frame: pd.DataFrame) -> str | None:
    if frame.shape[1] < 2 or frame.shape[1] > 3 or frame.empty:
        return None
    first = str(frame.iloc[0, 0]).strip().casefold().rstrip(":#")
    second = str(frame.iloc[0, 1]).strip().casefold().rstrip(":#")
    if first not in _KEY_VALUE_LABELS or second in _KEY_VALUE_LABELS:
        return None
    parts = [f"[SHEET {sheet_name}]"]
    for row in frame.itertuples(index=False, name=None):
        if len(row) < 2:
            continue
        key = "" if pd.isna(row[0]) else str(row[0]).strip().rstrip(":")
        value = "" if pd.isna(row[1]) else str(row[1]).strip()
        if key and value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def process_spreadsheet(path: Path) -> tuple[str, int, dict[str, Any]]:
    try:
        rows_truncated = False
        if path.suffix.lower() == ".csv":
            row_limit = min(100_000, settings.max_spreadsheet_rows)
            preview = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=2, header=None, encoding_errors="replace")
            key_value_text = _key_value_frame_to_text("CSV", preview)
            if key_value_text:
                frame = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=row_limit, header=None, encoding_errors="replace")
                text = _key_value_frame_to_text("CSV", frame) or key_value_text
                rows_truncated = len(frame.index) >= row_limit
                return text, 1, {"kind": "spreadsheet", "sheets": ["CSV"], "rows": len(frame.index), "rows_truncated": rows_truncated, "layout": "key_value"}
            frame = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=row_limit, encoding_errors="replace")
            sheets = {"CSV": frame}
            rows_truncated = len(frame.index) >= row_limit
        else:
            parts: list[str] = []
            sheet_names: list[str] = []
            total_rows = 0
            with pd.ExcelFile(path) as workbook:
                if len(workbook.sheet_names) > settings.max_spreadsheet_sheets:
                    raise DocumentProcessingError(f"Workbook has {len(workbook.sheet_names)} sheets; configured limit is {settings.max_spreadsheet_sheets}")
                rows_read = 0
                for sheet_name in workbook.sheet_names:
                    remaining = settings.max_spreadsheet_rows - rows_read
                    if remaining <= 0:
                        rows_truncated = True
                        break
                    preview = pd.read_excel(workbook, sheet_name=sheet_name, dtype=str, keep_default_na=False, nrows=2, header=None)
                    key_value_text = _key_value_frame_to_text(str(sheet_name), preview)
                    if key_value_text:
                        frame = pd.read_excel(workbook, sheet_name=sheet_name, dtype=str, keep_default_na=False, nrows=remaining, header=None)
                        parts.append(_key_value_frame_to_text(str(sheet_name), frame) or key_value_text)
                    else:
                        frame = pd.read_excel(workbook, sheet_name=sheet_name, dtype=str, keep_default_na=False, nrows=remaining)
                        parts.append(_spreadsheet_to_text(str(sheet_name), frame))
                    sheet_names.append(str(sheet_name))
                    rows_read += len(frame.index)
                    total_rows += len(frame.index)
                    if rows_read >= settings.max_spreadsheet_rows:
                        rows_truncated = True
                        break
            return "\n\n".join(parts), len(sheet_names), {"kind": "spreadsheet", "sheets": sheet_names, "rows": total_rows, "rows_truncated": rows_truncated}

        parts = []
        total_rows = 0
        for sheet_name, frame in sheets.items():
            total_rows += len(frame.index)
            parts.append(_spreadsheet_to_text(str(sheet_name), frame))
        return "\n\n".join(parts), len(sheets), {"kind": "spreadsheet", "sheets": list(sheets.keys()), "rows": total_rows, "rows_truncated": rows_truncated}
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError(f"Spreadsheet could not be parsed: {type(exc).__name__}") from exc

def process_document(path: Path) -> tuple[str, int | None, dict[str, Any]]:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise DocumentProcessingError(f"Unsupported file extension: {ext or '(none)'}")
    if ext == ".pdf":
        return process_pdf(path)
    if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        return process_image(path)
    return process_spreadsheet(path)
