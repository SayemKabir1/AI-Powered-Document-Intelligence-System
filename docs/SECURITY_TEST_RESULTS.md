# Security and regression test record

## Current remediation workspace

- Backend test command: `cd backend; pytest -q`
- Latest result in this code-editing workspace: **74 passed**.
- The regression suite covers authenticated session/CSRF behavior, cross-tenant document access, stale correction versions, before/after snapshots, initial administrator setup, demo workspace seeding, unauthenticated demo API reads/uploads, completed-job lease reconciliation, duplicate uploads across workspace owners, headerless CSV/XLSX, wrapped table items, label hijacking and financial label exclusions, hybrid hits without embeddings, and preservation of manual overrides after reprocessing.
- The tests use an in-memory SQLite database and mocked external model behavior where appropriate. They are not a substitute for the Antigravity security scripts running against a real isolated Docker stack.

## Controls tested in code-level automated tests

| Control | Status | Evidence / limits |
|---|---|---|
| API rejects missing session in authenticated mode | Passed | TestClient integration test removes the test auth override and receives 401. |
| Public demo API works without a session | Passed | TestClient integration test verifies anonymous search and upload using the dedicated demo identity. |
| Login/session/CSRF basics | Passed | Session cookies and CSRF enforcement covered in API tests. |
| Cross-tenant object access | Passed | A user cannot access another tenant's document by ID. |
| Versioned corrections | Passed | Stale correction versions return conflict; snapshot event is persisted. |
| First-admin setup | Passed | One-time setup is guarded by a conditional database update. |
| Upload signature/path checks | Passed | Existing path traversal, signature and corrupt file tests remain. |
| Duplicate upload | Passed | SHA-256 duplicate within workspace is rejected without revealing the existing document ID. |
| Worker lifecycle | Passed in unit/integration scenarios | Job/document state, retry classification, stale worker guard and completed lease reconciliation have tests; no live SIGTERM or Docker restart test. |
| Search | Passed in mocked API tests | Hybrid keyword hits without vectors and semantic fallback are covered; live vector ranking retest remains. |
| AI prompt-injection | Partial | Prompt override pattern and rules/model conflict warnings are implemented; no live Ollama adversarial retest was run here. |
| Security headers/production docs | Code implemented | Requires live ASGI/Nginx verification. |
| Container hardening | Dockerfiles/Compose templates updated | Docker CLI unavailable in this environment; image runtime not verified. |
| Dependency security | Not run | `npm audit`, `pip-audit`, Bandit and image scanning require dependency resolution/tooling. |
| Browser XSS and CSRF | Partial | React uses escaped text rendering and cookie CSRF; Playwright/browser test not run. |

## Important verification blockers

This editing environment did not provide a usable Docker daemon. Frontend dependencies were not installed and the Vite production build was not completed. PostgreSQL, browser automation, the original Antigravity load scripts, and dependency scanners were not rerun after the changes. Do not interpret the backend 65/65 result as a clean penetration test or production-readiness result.

## Reproduction on Windows PowerShell

From the project root:

```powershell
cd backend
python -m pip install -r requirements.txt
pytest -q
python -m compileall -q app tests scripts
```

In a separate terminal, from `frontend`:

```powershell
npm install
npm audit
npm run build
```

For Docker verification, use `docs/DEPLOYMENT_GUIDE.md` and run only against the isolated test copy/database first. Do not remove or prune existing Docker volumes.

## Document deletion regression checks

- Completed document deletion removes the stored source file and its document, processing-job, processing-event, and duplicate-reservation rows.
- Deleted content no longer appears in keyword search, and the same bytes can be uploaded again because the duplicate reservation is released.
- Queued/processing documents return `409 Conflict` without changing the source file or database record.
- Reviewer ownership scoping returns `404` for another owner's document and leaves it intact.
