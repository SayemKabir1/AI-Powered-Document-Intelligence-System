from __future__ import annotations
import json
import tempfile
import time
import sys
from pathlib import Path
import fitz
ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.document_processor import process_document


def main():
    with tempfile.TemporaryDirectory(prefix="docintel-1000-page-") as temp:
        path = Path(temp) / "synthetic_1000_pages.pdf"
        document = fitz.open()
        for index in range(1000):
            page = document.new_page(width=595, height=842)
            body = (
                f"Synthetic test page {index + 1:04d}\n"
                "Invoice Number: BENCH-0001\nInvoice Date: 2026-01-01\n"
                "Supplier: Performance Test Ltd\nCustomer: Internal QA\n"
                "Subtotal: 100.00\nTax: 15.00\nGrand Total: 115.00\n"
                "This generated page contains digital text only and is intended to test extraction throughput."
            )
            page.insert_textbox(fitz.Rect(50, 50, 540, 300), body, fontsize=11)
        document.save(path, garbage=4, deflate=True)
        document.close()
        size_bytes = path.stat().st_size
        start = time.perf_counter()
        text, page_count, metadata = process_document(path)
        elapsed = time.perf_counter() - start
        result = {
            "benchmark": "synthetic 1000-page digital PDF",
            "page_count_reported": page_count,
            "expected_page_count": 1000,
            "success": page_count == 1000 and len(text) > 0,
            "pdf_size_bytes": size_bytes,
            "extracted_text_characters": len(text),
            "elapsed_seconds": round(elapsed, 4),
            "pages_per_second": round(page_count / elapsed, 2) if elapsed else None,
            "kind": metadata.get("kind"),
            "limitations": "Digital text only; does not measure OCR latency for 1000 scanned pages or concurrent jobs.",
        }
        output = ROOT / "evaluation" / "benchmark_1000_pages.json"
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        print(f"Wrote {output}")

if __name__ == "__main__":
    main()
