from __future__ import annotations
import json
import platform
import sys
import time
from pathlib import Path
from statistics import mean, median
from math import ceil

ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_processor import process_document
from app.services.extractor import extract_invoice
from app.services.validation import validate_invoice

FIELDS = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency"]
LINE_FIELDS = ("description", "quantity", "unit_price", "amount")
SAMPLES_DIR = ROOT / "evaluation" / "multiformat_samples"
TRUTH_PATH = ROOT / "evaluation" / "multiformat_ground_truth.json"
OUTPUT_PATH = ROOT / "evaluation" / "multiformat_results.json"


def normalize(value):
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def matches(expected, actual):
    if expected is None or actual is None:
        return expected is actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= 0.01
    return normalize(expected) == normalize(actual)


def pct(num, den):
    return round(num / den, 4) if den else None


def evaluate_group(cases):
    field_hits = {name: 0 for name in FIELDS}
    field_totals = {name: 0 for name in FIELDS}
    line_hits = 0
    line_total = 0
    succeeded = 0
    failed = 0
    clean_validation = 0
    latencies = []
    methods = {}
    details = []

    for sample in cases:
        path = SAMPLES_DIR / sample["filename"]
        expected_fields = sample["fields"]
        expected_line = sample.get("line_item")
        if expected_line is not None:
            line_total += 1
        started = time.perf_counter()
        try:
            text, page_or_sheet_count, metadata = process_document(path)
            predicted, method = extract_invoice(text)
            errors, warnings = validate_invoice(predicted)
            elapsed = time.perf_counter() - started
            latencies.append(elapsed)
            methods[method] = methods.get(method, 0) + 1
            succeeded += 1
            for field in FIELDS:
                field_totals[field] += 1
                field_hits[field] += int(matches(expected_fields.get(field), getattr(predicted, field)))
            line_match = False
            if expected_line is not None and predicted.line_items:
                first = predicted.line_items[0]
                line_match = all(matches(expected_line.get(k), getattr(first, k)) for k in LINE_FIELDS)
                line_hits += int(line_match)
            clean_validation += int(len(errors) == 0)
            details.append({
                "filename": sample["filename"], "status": "success", "seconds": round(elapsed, 5),
                "method": method, "kind": metadata.get("kind"),
                "page_or_sheet_count": page_or_sheet_count,
                "field_matches": {field: matches(expected_fields.get(field), getattr(predicted, field)) for field in FIELDS},
                "line_item_exact_match": line_match if expected_line is not None else None,
                "validation_errors": errors, "validation_warnings": warnings,
            })
        except Exception as exc:
            elapsed = time.perf_counter() - started
            failed += 1
            latencies.append(elapsed)
            for field in FIELDS:
                field_totals[field] += 1
            details.append({"filename": sample["filename"], "status": "failed", "seconds": round(elapsed, 5), "error_type": type(exc).__name__, "error": str(exc)[:500]})

    all_hits = sum(field_hits.values())
    all_total = sum(field_totals.values())
    times = sorted(latencies)
    p95 = times[max(0, ceil(0.95 * len(times)) - 1)] if times else None
    total = len(cases)
    return {
        "dataset_size": total,
        "document_success_count": succeeded,
        "document_failure_count": failed,
        "document_success_rate": pct(succeeded, total),
        "document_failure_rate": pct(failed, total),
        "overall_field_exact_match_accuracy": pct(all_hits, all_total),
        "field_accuracy": {f: pct(field_hits[f], field_totals[f]) for f in FIELDS},
        "line_item_examples_evaluated": line_total,
        "line_item_exact_match_rate": pct(line_hits, line_total),
        "validation_arithmetic_clean_rate": pct(clean_validation, succeeded),
        "mean_processing_seconds": round(mean(latencies), 5) if latencies else None,
        "median_processing_seconds": round(median(latencies), 5) if latencies else None,
        "p95_processing_seconds": round(p95, 5) if p95 is not None else None,
        "extraction_methods": methods,
        "per_document": details,
    }


def evaluate_expected_rejections(cases):
    results = []
    for case in cases:
        path = SAMPLES_DIR / case["filename"]
        started = time.perf_counter()
        try:
            text, page_or_sheet_count, metadata = process_document(path)
            results.append({
                "filename": case["filename"], "expected_rejection": True,
                "rejected_as_expected": False, "status": "unexpectedly_processed",
                "seconds": round(time.perf_counter() - started, 5),
                "kind": metadata.get("kind"), "page_or_sheet_count": page_or_sheet_count,
                "extracted_text_characters": len(text),
            })
        except Exception as exc:
            results.append({
                "filename": case["filename"], "expected_rejection": True,
                "rejected_as_expected": True, "status": "rejected_as_expected",
                "seconds": round(time.perf_counter() - started, 5),
                "error_type": type(exc).__name__, "error": str(exc)[:500],
            })
    passed = sum(r["rejected_as_expected"] for r in results)
    return {"case_count": len(cases), "safe_rejection_count": passed, "safe_rejection_rate": pct(passed, len(cases)), "per_document": results}


def main():
    config = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    output = {
        "dataset": str(TRUTH_PATH.relative_to(ROOT)),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "notice": "Controlled synthetic test pack. Clean and degraded inputs are reported separately; expected invalid-input rejections are not counted as valid-document failures.",
        "clean_samples": evaluate_group(config["clean_samples"]),
        "degraded_samples": evaluate_group(config["degraded_samples"]),
        "expected_rejections": evaluate_expected_rejections(config["expected_rejections"]),
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))
    print(f"\nWrote {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
