# AI-Powered Document Intelligence System

A local-first invoice/document review application. It accepts PDF, JPG/JPEG, PNG, TIFF, XLSX, XLS and CSV files; extracts text and invoice fields; validates financial consistency; stores processing history; and provides a React review workspace with keyword, semantic and hybrid search.

## Current engineering status

This archive includes a remediation pass against the independent Antigravity audit. It adds an optional authenticated workspace mode, a recruiter-friendly shared demo mode, tenant/owner scoping, upload concurrency limits, safer worker state transitions, additive database compatibility migrations, correction versioning and audit snapshots, search/query optimizations, extraction/validation fixes, and separate development/production container definitions.

The corrected source workspace's backend suite currently reports **74 passed**. This is a code/test result from the remediation workspace, not proof that Docker Compose, the Windows runtime, the production image build, PostgreSQL deployment, browser E2E, or 1,000-user capacity has been validated. See `docs/AUDIT_REMEDIATION_MATRIX.md` and `docs/DEPLOYMENT_GUIDE.md` before deployment.

**Production-readiness warning:** Do not expose this application directly to the Internet. Use HTTPS through a trusted reverse proxy, set unique secrets, review tenant administration, and complete the outstanding runtime, dependency, and performance checks first. The audit previously measured a 25-user mixed-workload ceiling and a failure at 50 users; the remediation has not yet been re-benchmarked against that load profile.

## Architecture

```text
React UI (same-origin requests)
          |
          v
FastAPI API ---- PostgreSQL (production) / SQLite WAL (local development)
    |                        |
    |                        +-- documents, users, tenants, events, jobs
    |
    +-- private file storage
    |
    +-- durable processing_jobs queue --> separate worker
                                           |
                                           +-- PyMuPDF / Tesseract
                                           +-- pandas / openpyxl / xlrd
                                           +-- optional local Ollama
```

Original files use generated UUID-based storage names and are not served from a public static directory. Processing runs in a separate worker. The worker uses leases, conditional worker ownership, bounded retry behavior, and atomic final state persistence. Manual corrections are version-checked and recorded with before/after snapshots.

## Requirements

- Python 3.11+ (project dependencies currently target Python 3.13 containers).
- Node.js 22+ for the Vite 8 frontend.
- Tesseract OCR available on `PATH` for scanned PDFs and images.
- Optional local Ollama with `qwen2.5:3b` and `nomic-embed-text` models.
- Docker Desktop with Docker Compose for the container workflows.

## Run locally with Python and Node (Windows PowerShell)

1. Open the project root in PowerShell.
2. Create a backend environment and install dependencies:

   ```powershell
   cd backend
   py -3.13 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. In Terminal 1, from `backend`, start the API:

   ```powershell
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

4. In Terminal 2, from `backend` with the same environment activated, start the worker:

   ```powershell
   python -m app.worker
   ```

5. In Terminal 3, from the `frontend` folder, install and run the UI in the same no-login mode:

   ```powershell
   $env:VITE_DEMO_MODE = "true"
   npm install
   npm run dev
   ```

6. Open `http://localhost:5173`. The backend `.env.example` also sets `DEMO_MODE=true`, so no login screen or password is required. Visitors share the same demo workspace. Use synthetic/sample documents only; all visitors can inspect, upload, correct and reprocess documents in that workspace.

Health check: `http://127.0.0.1:8000/health`. API docs are enabled in development at `http://127.0.0.1:8000/docs` only.

## Run with Docker Compose (development)

1. From the project root, prepare the backend environment file (optional but recommended for enabling Ollama):

   ```powershell
   Copy-Item .\backend\.env.example .\backend\.env
   ```

2. Start the development stack:

   ```powershell
   docker compose up --build -d
   ```

3. Check services and logs:

   ```powershell
   docker compose ps
   docker compose logs -f backend worker frontend
   ```

4. Open `http://localhost:5173`. The supplied Compose profile enables Public demo mode, so no account or password is required. By default, the backend is bound to `127.0.0.1:8000` and the frontend to `127.0.0.1:5173`. To run the corrected copy alongside an existing local stack, use alternate host ports, for example `$env:BACKEND_HOST_PORT=18000; $env:FRONTEND_HOST_PORT=15173; docker compose up --build -d`.

To enable local AI, set `OLLAMA_ENABLED=true` in `backend/.env`, then run:

```powershell
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull nomic-embed-text
docker compose restart backend worker
```

Do not run destructive Docker cleanup commands against this project's named volumes. The local database and storage directory contain persistent data.

## Access modes

- **Public demo mode (enabled by the supplied development Compose profile):** no login or password is shown or required. A dedicated `public-demo@local.invalid` identity provides a shared demo workspace. The first demo startup creates that identity if needed and associates only legacy, unscoped document rows with its workspace; it does not delete document rows or uploaded files.
- In demo mode, all visitors share the same workspace and can search, upload, compare, correct, reprocess and permanently delete documents. Changes and deletions are visible to other visitors. Do not use confidential, personal or production documents in this mode. Do not expose a demo deployment without HTTPS, a trusted reverse proxy, and appropriate rate/resource limits.
- **Authenticated mode (optional):** set `DEMO_MODE=false` and use the normal first-admin setup, signed `HttpOnly` session cookie and CSRF cookie/header pair. Reviewers can access documents they uploaded; administrators can access documents in their workspace.
- Manual corrections require the current document `version`, return `409 Conflict` for stale updates, and write before/after snapshots to processing history.
- Document-library cleanup: select a document and choose **Delete**, or use **Delete document** in its review panel. A confirmation prompt explains that the original file and all associated records are permanently removed. Documents still queued or processing cannot be deleted until they reach a terminal state. In authenticated mode the same tenant/owner visibility rules apply; in public demo mode deletion affects the shared workspace for every visitor.

## Main API routes

- Authenticated mode only: `GET /api/auth/setup-status`, `POST /api/auth/setup`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`, `POST /api/auth/users`, `GET /api/auth/users`. These routes are not mounted in Public demo mode.
- `POST /api/documents/upload` (bounded multi-file upload; duplicate content is rejected within the workspace by default)
- `GET /api/documents`, `GET /api/documents/stats`
- `GET /api/documents/{id}`, `GET /api/documents/{id}/status`, `GET /api/documents/{id}/result`, `GET /api/documents/{id}/history`
- `DELETE /api/documents/{id}` (permanently deletes the original stored file, extracted data, search embedding, validation findings, duplicate reservation, processing jobs and history; queued/processing documents are protected with `409 Conflict`)
- `PATCH /api/documents/{id}/corrections` (requires `expected_version`)
- `POST /api/documents/{id}/reprocess`
- `POST /api/documents/compare`
- `GET /api/search` (keyword, semantic or hybrid search; semantic modes fall back to keyword when embeddings are unavailable)
- `GET /health` (minimal health response)

## Tests and evaluation

Run from `backend`:

```powershell
pytest -q
python -m compileall -q app tests scripts
python scripts/evaluate.py
python scripts/evaluate_multiformat.py
python scripts/benchmark_1000_pages.py
```

The supplied evaluation fixtures are synthetic. Do not present their scores as production OCR accuracy. The 1,000-page benchmark uses a synthetic **digital-text** PDF; it is not a 1,000-page scanned OCR benchmark. See `docs/EVALUATION.md` and `evaluation/` for dataset scope and measured result files.

## Production deployment

A separate `compose.prod.yaml` defines PostgreSQL, Ollama, a non-root backend/worker image, and a non-root Nginx frontend. Read `docs/DEPLOYMENT_GUIDE.md` before using it. Production requires:

- A strong random `POSTGRES_PASSWORD` in a local `.env` file that is never committed. Authenticated mode additionally requires `SESSION_SECRET` (at least 32 characters) and `BOOTSTRAP_TOKEN` (at least 24 characters).
- Explicit allowed `CORS_ORIGINS`.
- For a no-login recruiter demo, set `DEMO_MODE=true` in `.env` so the backend and built frontend use the same mode. The demo has one shared admin workspace with no per-visitor isolation; it allows writes and processing, so deploy only a sanitized sample dataset. Keep `DEMO_MODE=false` for private/real customer data.
- A trusted TLS reverse proxy in front of the loopback-bound frontend. Secure cookies and HSTS require HTTPS; the Compose frontend port itself is not a TLS terminator.
- A backup and restore plan for PostgreSQL and the shared app-storage volume.
- A PostgreSQL migration/backup rehearsal before upgrading an existing deployment.

The included application session implementation is a first-party local account/session system, not OIDC, SSO, MFA, password recovery, or a completed enterprise identity solution. Review those requirements before a shared organizational rollout.

## Known limitations and unverified areas

- The audit's 1,000-user ramp was stopped at 50 VUs after the safety threshold was crossed. The prior audited system sustained 25 mixed read-heavy users and failed at 50. The corrected code has not been load-tested again, so no higher concurrency capacity is claimed.
- Local vector ranking still scans a bounded set of stored JSON embeddings in Python. PostgreSQL is configured for production persistence, but the app does not yet use pgvector. At larger document counts, use a vector index and/or a dedicated search service.
- No real-world labeled OCR corpus is included. Degraded scans still need human review; extraction success is not equivalent to extraction accuracy.
- Authentication is not an enterprise identity provider; MFA, password reset, email verification, session revocation, and full security monitoring are not implemented.
- The frontend production build, `npm audit`, Python dependency CVE scan, production Docker build, Windows end-to-end UI, PostgreSQL runtime, and live security/load retests could not be executed in this editing environment. Follow the verification matrix and local steps in `docs/AUDIT_REMEDIATION_MATRIX.md`.
- Database compatibility migration is additive and does not drop tables or delete rows. Take a verified backup before production upgrades; test the migration on a copy first.

## Project documents

- `docs/ARCHITECTURE.md`
- `docs/DATABASE_SCHEMA.md`
- `docs/PROJECT_CHECKLIST.md`
- `docs/SECURITY.md`
- `docs/SECURITY_TEST_RESULTS.md`
- `docs/EVALUATION.md`
- `docs/AUDIT_REMEDIATION_MATRIX.md`
- `docs/DEPLOYMENT_GUIDE.md`
- `docs/AI_DISCLOSURE.md`
- `docs/WALKTHROUGH_SCRIPT.md`
- `docs/RECRUITER_DEMO.md`
