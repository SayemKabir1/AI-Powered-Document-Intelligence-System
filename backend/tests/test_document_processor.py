from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import pandas as pd
import pytest

from app.services.document_processor import process_document, process_spreadsheet, DocumentProcessingError
from app.services.extractor import extract_invoice


def test_csv_invoice_table_extracts_fields_and_line_items(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "ollama_enabled", False)
    path = tmp_path / "invoice.csv"
    pd.DataFrame([{
        "Invoice Number": "CSV-1001",
        "Invoice Date": "2026-04-15",
        "Supplier Name": "Example Supplier Ltd",
        "Customer Name": "Example Customer",
        "Subtotal": 100.0,
        "Tax": 15.0,
        "Total": 115.0,
        "Currency": "USD",
        "Description": "Consulting",
        "Quantity": 2,
        "Unit Price": 50.0,
        "Amount": 100.0,
    }]).to_csv(path, index=False)
    text, sheets, metadata = process_spreadsheet(path)
    data, method = extract_invoice(text)
    assert method == "rules"
    assert sheets == 1
    assert metadata["kind"] == "spreadsheet"
    assert data.invoice_number == "CSV-1001"
    assert data.supplier_name == "Example Supplier Ltd"
    assert data.subtotal == 100
    assert data.tax == 15
    assert data.total == 115
    assert data.line_items[0].description == "Consulting"
    assert data.line_items[0].quantity == 2
    assert data.line_items[0].unit_price == 50
    assert data.line_items[0].amount == 100


def test_xlsx_multiple_sheets_are_parsed(tmp_path):
    path = tmp_path / "multi.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"Invoice Number": ["X-1"], "Total": [10]}).to_excel(writer, sheet_name="Invoice", index=False)
        pd.DataFrame({"Note": ["supporting data"]}).to_excel(writer, sheet_name="Notes", index=False)
    text, sheet_count, metadata = process_document(path)
    assert sheet_count == 2
    assert metadata["sheets"] == ["Invoice", "Notes"]
    assert "Invoice Number: X-1" in text
    assert "[SHEET Notes]" in text


def test_corrupt_pdf_is_reported_as_processing_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF- this is not a complete PDF")
    with pytest.raises(DocumentProcessingError):
        process_document(path)


def test_ocr_image_when_tesseract_is_installed(tmp_path):
    import shutil
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is not installed in this test environment")
    image = Image.new("RGB", (1200, 400), "white")
    draw = ImageDraw.Draw(image)
    # Default PIL font is available in a clean environment; large text makes OCR robust.
    draw.text((40, 50), "Invoice Number INV-2026-7", fill="black", font=ImageFont.load_default(size=42))
    draw.text((40, 160), "Grand Total 115.00", fill="black", font=ImageFont.load_default(size=42))
    path = tmp_path / "invoice.png"
    image.save(path)
    text, frames, metadata = process_document(path)
    assert frames == 1
    assert metadata["kind"] == "image"
    assert "Invoice Number" in text or "Invoice Number".lower() in text.lower()
    assert "115.00" in text


def test_scanned_pdf_ocr_when_tesseract_is_installed(tmp_path):
    import io
    import shutil
    import fitz
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is not installed in this test environment")
    image = Image.new("RGB", (1400, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    draw.text((35, 45), "Invoice Number SCAN-2026-7", fill="black", font=font)
    draw.text((35, 165), "Grand Total 215.00", fill="black", font=font)
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(35, 50, 560, 250), stream=image_bytes.getvalue())
    pdf_path = tmp_path / "scanned.pdf"
    pdf.save(pdf_path)
    pdf.close()
    text, pages, metadata = process_document(pdf_path)
    assert pages == 1
    assert metadata["kind"] == "pdf"
    assert "SCAN-2026-7" in text
    assert "215.00" in text


def test_oversized_image_is_rejected_before_copy():
    from app.services.document_processor import _ocr_image, MAX_IMAGE_PIXELS
    class HugeImage:
        width = MAX_IMAGE_PIXELS + 1
        height = 2
    with pytest.raises(DocumentProcessingError, match="pixel processing limit"):
        _ocr_image(HugeImage())


def test_headerless_key_value_csv_is_not_consumed_as_headers(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "ollama_enabled", False)
    path = tmp_path / "key-value.csv"
    path.write_text(
        "Invoice Number,KV-101\nInvoice Date,2026-06-01\nSupplier Name,Key Value Supplies\n"
        "Customer Name,Example Buyer\nSubtotal,100\nTax,15\nTotal,115\nCurrency,USD\n",
        encoding="utf-8",
    )
    text, pages, metadata = process_spreadsheet(path)
    data, _ = extract_invoice(text)
    assert pages == 1
    assert metadata["layout"] == "key_value"
    assert data.invoice_number == "KV-101"
    assert data.supplier_name == "Key Value Supplies"
    assert data.total == 115


def test_headerless_key_value_xlsx_is_detected(tmp_path):
    path = tmp_path / "key-value.xlsx"
    frame = pd.DataFrame([
        ["Invoice Number", "KV-XLSX-1"], ["Supplier Name", "Workbook Supplies"],
        ["Subtotal", "20"], ["Tax", "3"], ["Total", "23"], ["Currency", "BDT"],
    ])
    frame.to_excel(path, header=False, index=False)
    text, sheets, metadata = process_spreadsheet(path)
    data, _ = extract_invoice(text)
    assert sheets == 1
    assert "key_value" not in metadata or metadata["kind"] == "spreadsheet"
    assert data.invoice_number == "KV-XLSX-1"
    assert data.supplier_name == "Workbook Supplies"
    assert data.total == 23


def test_application_sqlite_connections_enable_secure_delete():
    from app.db import engine
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as connection:
        assert int(connection.exec_driver_sql("PRAGMA secure_delete").scalar()) == 1

def test_adaptive_binarization_fallback_recovers_faint_invoice_text(monkeypatch):
    import shutil
    import numpy as np
    import app.services.document_processor as document_processor
    from PIL import ImageFilter

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is not installed in this test environment")

    width, height = 1600, 700
    rng = np.random.default_rng(2026)

    gradient = np.tile(
        np.linspace(232, 248, width, dtype=np.float32),
        (height, 1),
    )
    background = np.clip(
        gradient + rng.normal(0, 1.5, (height, width)),
        0,
        255,
    ).astype(np.uint8)

    image = Image.fromarray(background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)

    lines = [
        "INVOICE NUMBER: FAINT-2026-01",
        "INVOICE DATE: 2026-10-31",
        "SUPPLIER: EXAMPLE TECHNOLOGY LTD",
        "DESCRIPTION: WIRELESS MOUSE",
        "GRAND TOTAL: 157.50",
    ]

    for index, line in enumerate(lines):
        draw.text(
            (80, 90 + index * 105),
            line,
            fill=198,
            font=font,
        )

    faint_image = image.filter(
        ImageFilter.GaussianBlur(0.4)
    ).convert("RGB")

    original_ocr = document_processor._run_tesseract_ocr
    calls = 0

    def force_weak_first_pass(candidate):
        nonlocal calls
        calls += 1

        if calls == 1:
            return "", 0.0

        return original_ocr(candidate)

    monkeypatch.setattr(
        document_processor,
        "_run_tesseract_ocr",
        force_weak_first_pass,
    )

    text, confidence = document_processor._ocr_image_detailed(
        faint_image
    )

    normalized = " ".join(text.upper().split())

    assert calls == 2, "Adaptive OCR fallback was not executed"
    assert "INVOICE" in normalized
    assert "GRAND TOTAL" in normalized
    assert confidence is not None
    assert confidence >= 60
def test_estimate_skew_angle_corrects_small_rotations():
    from app.services.document_processor import _estimate_skew_angle

    font = ImageFont.load_default(size=36)
    lines = [
        "INVOICE NUMBER: QA-2026-001",
        "INVOICE DATE: 2026-10-30",
        "SUPPLIER: EXAMPLE TECHNOLOGY LTD",
        "CUSTOMER: QA TEST CUSTOMER",
        "DESCRIPTION: WIRELESS MOUSE",
        "QUANTITY: 2 UNIT PRICE: 25.00",
        "SUBTOTAL: 50.00",
        "TAX: 7.50",
        "GRAND TOTAL: 57.50",
    ]

    for rotation in (2.0, -2.0):
        image = Image.new("RGB", (1200, 900), "white")
        draw = ImageDraw.Draw(image)

        for index, line in enumerate(lines):
            draw.text(
                (80, 80 + index * 75),
                line,
                fill="black",
                font=font,
            )

        rotated = image.rotate(
            rotation,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor="white",
        )

        correction = _estimate_skew_angle(rotated)

        assert abs(correction + rotation) <= 0.6, (
            f"Incorrect deskew estimate for rotation {rotation}: "
            f"{correction}"
        )
