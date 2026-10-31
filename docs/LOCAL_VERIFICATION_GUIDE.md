# Local Verification Guide (Windows PowerShell)

This guide verifies the four implementation areas requested for the assignment: AI information extraction (Task 2), backend API and background processing (Task 4), database/search (Task 5), and frontend (Task 6). The local rules-based path does not need a paid API. Ollama is optional.

## 1. Before you start

Install a supported Python version (Python 3.11 or newer), Node.js LTS with npm, and optionally Git. To use the Docker route, install Docker Desktop and start its engine. OCR for image/scanned-PDF input also requires the Tesseract OCR executable; if Tesseract is not installed, digital PDF and spreadsheet tests still exercise the local pipeline, but OCR-dependent input may fail or return limited text.

Extract this ZIP to a short path, for example `C:\work\AI-Powered-Document-Intelligence-System`. Do not put real financial documents or secrets into the demo project.

## 2. Install the backend in a clean environment

Open PowerShell in the extracted project folder, then run:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item ..\.env.example .env
```

If Python 3.13 is not installed, replace `py -3.13` with a version available on your machine (for example `py -3.12`). If PowerShell blocks activation, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again. Do not overwrite a `.env` that already contains settings you need.

Verify the important package versions after installing, because this reviewed workspace could not download the updated dependency versions itself:

```powershell
python -c "import fitz, multipart; print('PyMuPDF:', fitz.VersionBind); print('python-multipart:', multipart.__version__)"
python -m pip check
```

Confirm PyMuPDF is at least `1.28.0` and `python-multipart` at least `0.0.30`. If not, do not process untrusted files until `pip install -r requirements.txt --upgrade` completes successfully and you confirm the versions.

## 3. Start the app in three terminals

Keep the same project checkout and `.env` for all terminals. The backend API and worker must use the same database and storage settings.

**Terminal 1: API**

```powershell
cd C:\work\AI-Powered-Document-Intelligence-System\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2: durable processing worker**

```powershell
cd C:\work\AI-Powered-Document-Intelligence-System\backend
.\.venv\Scripts\Activate.ps1
python -m app.worker
```

Leave this terminal running. It claims persisted queue jobs, processes them, retries transient failures up to the configured attempt limit, and records status/history in the database.

**Terminal 3: React frontend**

```powershell
cd C:\work\AI-Powered-Document-Intelligence-System\frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173` for the UI and `http://127.0.0.1:8000/docs` for interactive API docs. The health endpoint is `http://127.0.0.1:8000/health`. If `npm install` or `npm run build` fails, record the error; a source syntax check is not the same as a working browser build.

## 4. Task-by-task checks

### Task 2: extraction without a paid API

1. Upload a small **digital-text PDF invoice** (one you are permitted to use) with an invoice number/date, supplier/customer, subtotal, tax, total, currency, and a clear line-item table. You can also upload CSV/XLSX.
2. Watch the queue state in the UI. A fresh upload should first be `pending`/`queued`; the worker should move it through `processing` to `completed`, or to `failed` with an error.
3. Open the extracted result. Check all fields, line-item quantities/prices/amounts, evidence snippets, and validation warnings. Missing/uncertain fields should remain null or be flagged rather than guessed.
4. Use Swagger to call `GET /api/documents/{document_id}/result` and inspect the structured JSON.
5. For scanned PDF/JPG/PNG/TIFF, confirm Tesseract is installed and on PATH. OCR output depends heavily on scan quality, language data and layout. Validate it manually; do not take the small synthetic CSV evaluation score as real-world accuracy.

### Task 4: API and background worker

1. Upload multiple supported files from the UI, or use `POST /api/documents/upload` in Swagger. The API returns accepted document IDs without waiting for OCR.
2. Call `GET /api/documents/{document_id}/status` repeatedly. Check `document_status`, `queue_status`, `attempt_count`, `max_attempts`, and any `last_error`.
3. Stop and restart the API while the worker remains running, then restart the worker while keeping the database/storage intact. Check the recorded queue status and observe whether queued/expired work recovers. Do this only with disposable test documents. This is a manual smoke test, not a substitute for production crash/concurrency testing.
4. To exercise failure/reprocessing, use a disposable file whose extension is `.pdf` and which starts with `%PDF-` but is not a valid PDF. It should eventually become `failed` after retries; use **Reprocess** to queue it again. The file will fail again, so do not use an important document.
5. Check `GET /api/documents/{document_id}/history` for upload, job-start, retry/failure, correction and reprocess events.

### Task 5: database, filtering and semantic search

Use `GET /api/search` in Swagger. Examples:

```text
/api/search?q=INV-100&mode=keyword
/api/search?q=invoice&mode=hybrid&state=completed&file_type=pdf
/api/search?supplier=Example&invoice_number=INV-100&date_from=2026-01-01&date_to=2026-12-31
/api/documents?state=failed&file_type=pdf&limit=20&offset=0
```

Check results against the documents you uploaded and confirm filters narrow the result set. Without local embedding vectors, semantic/hybrid mode intentionally reports `mode_used: keyword_fallback`; that is a transparent fallback, not semantic-model success.

**Optional real semantic/model path (no paid key):** install Ollama, start it, run `ollama pull qwen2.5:3b` and `ollama pull nomic-embed-text`. In `backend\.env`, set `OLLAMA_ENABLED=true`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`, and ensure `OLLAMA_MODEL` / `OLLAMA_EMBEDDING_MODEL` match pulled models. Restart the API and worker, then reprocess a completed document to create an embedding. Search in `semantic` or `hybrid` mode and inspect `mode_used`. Model behavior and resource use depend on your machine. For Docker, the host Ollama URL is usually `http://host.docker.internal:11434` from containers.

### Task 6: React review workflow

1. Select several files in the upload control and submit them together.
2. Check the list refreshes and status changes as the worker processes jobs.
3. Use keyword search and the state/type/supplier/invoice/date filters.
4. Open a completed document, review extracted fields, evidence and validation messages.
5. Correct one scalar field and add/edit/remove a line item, then save. Confirm the change persists after reloading the document and the history includes a manual-correction event.
6. Select two or more completed documents for comparison; select one or more fields and inspect reported differences.
7. Use Reprocess on a failed disposable document.

## 5. Automated checks

Run these from the `backend` directory with the virtual environment active:

```powershell
pytest -q
python -m compileall -q app tests scripts
python scripts/evaluate.py
python scripts/benchmark_1000_pages.py
```

The generated evaluation corpus is only a small synthetic CSV sample; its measured accuracy is not a claim about real scans. The 1,000-page benchmark exercises a generated **digital-text** PDF, not scanned OCR.

From the `frontend` directory, run:

```powershell
npm audit
npm run build
```

Resolve dependency/build errors before submission. `npm audit` can report new findings because package advisories change over time.

## 6. Docker alternative

From the project root, copy `.env.example` to `backend/.env` if it is not already there, start Docker Desktop, then run:

```powershell
docker compose up --build
```

Check `docker compose ps`, `docker compose logs -f backend`, and `docker compose logs -f worker`. The UI is at `http://localhost:5173`; the API docs are at `http://localhost:8000/docs`. Docker availability was not verified during this review, so use the three-terminal route if Compose cannot start.

## Safety and known boundaries

This is an assignment MVP and must remain local-only until authentication/object-level authorization, parser isolation, retention/deletion controls, quotas/rate limiting, and operational monitoring are added. Never put real invoices, personal financial data, passwords or API keys into screenshots or a recorded walkthrough. Do not embed a shared production API key in frontend code.
