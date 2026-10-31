# Recorded walkthrough plan (target: 5–7 minutes)

This is a script for the submitter to record after starting the app locally. It is not a recording and should only be marked complete after an actual video has been produced.

## 1. Introduction (30 seconds)

“ This is my AI-Powered Document Intelligence System. It processes PDFs, scanned images and spreadsheet files, extracts invoice fields, validates financial totals, and lets a reviewer search and correct records. The MVP uses free, local-first tools and does not require a paid API key. ”

## 2. Architecture and startup (45 seconds)

Show `docs/ARCHITECTURE.md`, `docs/DATABASE_SCHEMA.md` and the README setup instructions. Start FastAPI on `127.0.0.1:8000` and the Vite UI on `localhost:5173`. Show the API health response and `/docs`. Do not display real credentials or confidential documents.

## 3. Upload and processing (60–90 seconds)

Upload one synthetic CSV invoice and one generated digital PDF. Show that documents are accepted and appear in the list. Open a completed record and point to the extracted invoice number/date, supplier/customer, currency, subtotal, tax, total, line items and field evidence. Explain that scanned documents use Tesseract OCR when installed, and Ollama extraction is optional.

## 4. Validation and manual review (60 seconds)

Show a record that has a missing required field or an arithmetic mismatch, if one is present in the demonstration set. Explain that warnings/errors are deterministic checks; fields the fallback cannot determine remain empty. Correct one field in the UI, save it, and show that the result and validation state update.

## 5. Search, filters and cross-verification (45–60 seconds)

Search by supplier/invoice text, then show status/file-type/supplier/invoice/date filters. If a local embedding model is installed and verified, demonstrate semantic search and say which mode the API reports. Otherwise explicitly demonstrate keyword fallback. If two suitable completed records are available, select both in the Cross-document verification UI and show selected-field differences. The comparison API supports line-item comparison too, but arbitrary row alignment is not guaranteed.

## 6. Tests and measured evaluation (45 seconds)

Show the `pytest -q` result, `evaluation/latest_results.json`, `evaluation/ground_truth.json` and `evaluation/benchmark_1000_pages.json`. State that 100% field exact-match in the five-document synthetic dataset is limited to that generated dataset. The 1,000-page result measures digital PDF text extraction, not a 1,000-page scanned OCR run or complete end-to-end throughput.

## 7. Security and limitations (45–60 seconds)

Show `docs/SECURITY.md`. Mention upload signature/size checks, sanitized storage names, processing caps, API key enforcement and tests for malformed input. Explicitly note the open gaps: no multi-user identity/tenant isolation, browser-visible shared API keys are demo-only, accepted jobs are persisted in the SQL queue with bounded retries, while full process-kill/restart behavior still needs integration testing, and local-model/large OCR performance depends on the target computer.

## 8. Closing (15 seconds)

Summarize supported formats, extraction/validation/API/UI, tests and next production steps. Do not claim security certification, real-world accuracy, verified LLM inference or functionality that was not shown in the recording.

## Suggested demo data

Use only the generated examples under `evaluation/sample_docs/` or synthetic documents you create. Avoid recording credentials, private financial data, API keys or personal information.
