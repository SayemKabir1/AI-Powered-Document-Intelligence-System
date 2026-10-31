from __future__ import annotations
import json
import platform
import sys
import time
from pathlib import Path
from statistics import mean
from math import ceil

ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_processor import process_document
from app.services.extractor import extract_invoice
from app.services.validation import validate_invoice


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


def main():
    truth_path = ROOT / "evaluation" / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    field_names = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency"]
    field_hits = {name: 0 for name in field_names}
    field_totals = {name: 0 for name in field_names}
    line_item_hits = 0
    line_item_total = 0
    validation_consistent = 0
    succeeded = 0
    failed = 0
    latencies = []
    methods = {}
    details = []

    for sample in truth:
        path = ROOT / "evaluation" / "sample_docs" / sample["filename"]
        expected_line = sample.get("line_item")
        if expected_line is not None:
            line_item_total += 1
        started = time.perf_counter()
        try:
            text, page_count, metadata = process_document(path)
            expected = sample["fields"]
            predicted, method = extract_invoice(text)
            errors, warnings = validate_invoice(predicted)
            elapsed = time.perf_counter() - started
            latencies.append(elapsed)
            methods[method] = methods.get(method, 0) + 1
            succeeded += 1
            for field in field_names:
                field_totals[field] += 1
                field_hits[field] += int(matches(expected.get(field), getattr(predicted, field)))
            if expected_line is not None and predicted.line_items:
                first = predicted.line_items[0]
                line_item_hits += int(all(matches(expected_line.get(k), getattr(first, k)) for k in ("description", "quantity", "unit_price", "amount")))
            validation_consistent += int(len(errors) == 0)
            details.append({"filename": sample["filename"], "status": "success", "seconds": round(elapsed, 5), "method": method, "errors": errors, "warnings": warnings, "page_or_sheet_count": page_count, "kind": metadata.get("kind")})
        except Exception as exc:
            failed += 1
            details.append({"filename": sample["filename"], "status": "failed", "error_type": type(exc).__name__})
            for field in field_names:
                field_totals[field] += 1

    total_docs = len(truth)
    total_fields = sum(field_totals.values())
    total_hits = sum(field_hits.values())
    results = {
        "dataset": str(truth_path.relative_to(ROOT)),
        "dataset_size": total_docs,
        "synthetic_dataset_notice": "These are generated spreadsheet examples only. Results are not representative of real-world scanned invoices or arbitrary layouts.",
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "document_success_rate": round(succeeded / total_docs, 4) if total_docs else None,
        "document_failure_rate": round(failed / total_docs, 4) if total_docs else None,
        "overall_field_exact_match_accuracy": round(total_hits / total_fields, 4) if total_fields else None,
        "field_accuracy": {field: round(field_hits[field] / field_totals[field], 4) if field_totals[field] else None for field in field_names},
        "line_item_examples_evaluated": line_item_total,
        "line_item_exact_match_rate": round(line_item_hits / line_item_total, 4) if line_item_total else None,
        "validation_arithmetic_clean_rate": round(validation_consistent / succeeded, 4) if succeeded else None,
        "mean_processing_seconds": round(mean(latencies), 5) if latencies else None,
        "median_processing_seconds": round(sorted(latencies)[len(latencies)//2], 5) if latencies else None,
        "p95_processing_seconds": round(sorted(latencies)[max(0, ceil(0.95 * len(latencies)) - 1)], 5) if latencies else None,
        "extraction_methods": methods,
        "per_document": details,
    }
    output_path = ROOT / "evaluation" / "latest_results.json"
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"\nWrote {output_path}")

if __name__ == "__main__":
    main()
