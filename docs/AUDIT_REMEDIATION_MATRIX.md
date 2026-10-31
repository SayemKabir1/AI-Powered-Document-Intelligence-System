# Antigravity audit remediation matrix

**Project:** AI-Powered Document Intelligence System
**Audit source:** Antigravity reports dated 30 October 2026
**Remediation snapshot:** 30 October 2026
**Backend verification in the remediation workspace:** 74 passed

## Executive status

The code changes below address the defects that could be changed and regression-tested in this workspace. Passing unit/integration tests are not a substitute for a fresh Docker, browser, PostgreSQL, load, or penetration test. The original audit measured a maximum of 25 mixed read-heavy virtual users and stopped its ramp at 50 VUs after a 17.48% error rate. **No post-remediation concurrency capacity is claimed.**

| Finding | Priority | Remediation status | Changes / remaining limitation |
|---|---|---|---|
| F-001 | P0 | Implemented in source; load retest pending | Upload route is synchronous (DB/filesystem work off event loop), upload concurrency is bounded, batches are capped, body length is checked, and SQLite WAL/busy timeout are configured. Must rerun 30+ concurrent upload test in isolated Docker. |
| F-002 | P0 | Implemented baseline session/tenant control; enterprise identity remains out of scope | Added signed HttpOnly sessions, CSRF token, password hashing, first-admin bootstrap, roles, tenant/owner document scoping, and admin user management. Removed browser `VITE_API_KEY`. Not OIDC/SSO/MFA/password recovery/session revocation; requires security review before shared rollout. |
| F-003 | P0 | Implemented; fault-injection runtime retest pending | Worker claim/document processing state and final document/job state are committed together; completed expired jobs are reconciled instead of reprocessed; finalization checks worker ownership; retries are classified. |
| F-004 | P1 | Partially implemented; benchmark retest pending | Ollama embedding request occurs before DB access, semantic query projects IDs/vectors, DB connection is released before scoring, pure semantic mode avoids keyword ILIKE, hybrid unions keyword hits. Python-side vector ranking still scans up to 10,000 stored JSON vectors; pgvector and post-fix 50-VU test remain outstanding. |
| F-005 | P1 | Implemented in source; 10k query benchmark pending | Added normalized invoice/supplier/date columns and indexes. Duplicate detection uses scalar indexed lookup rather than loading full `Document` rows. List/search result paths use metadata-only `load_only` projections. |
| F-006 | P1 | Implemented with regression coverage | Explicit/specific labels take priority; generic From/To/Date require delimiters; tax ID/TIN lines are excluded from tax amount extraction; Subtotal is excluded from grand-total extraction. |
| F-007 | P1 | Implemented with regression coverage | CSV and XLSX key/value layouts are detected before treating the first row as headers. |
| F-008 | P1 | Partially implemented | Prompt-override text and conflicting labels bypass Ollama; deterministic rules are compared with model results and conflicts produce review warnings; ungrounded values are nulled. Substring evidence is not a complete prompt-injection boundary. Adversarial live-model retest and stronger structured evidence anchoring remain required. |
| F-009 | P1 | Implemented with regression coverage | Cross-document comparison cannot return `matching=true` when core identity fields (invoice number, supplier, total) are missing. Line items are normalized/sorted before comparison. |
| F-010 | P1 | Implemented in source | Empty/uninformative documents are not embedded; Nomic query/document prefixes are used; a configurable cosine minimum similarity is enforced. Real ranking quality still needs a labeled test set and retest. |
| F-011 | P1 | Implemented with regression coverage | Added SQLAlchemy optimistic version column and required `expected_version`; stale edits return 409; manual overrides are retained across reprocessing; correction/reprocess before-state snapshots are stored in processing events. |
| F-012 | P1 | Partially implemented | Default lease reduced to 120 seconds, heartbeats are worker-owned, SIGTERM/SIGINT stop new job claims, and Compose uses 180-second stop grace. An in-flight synchronous job is allowed to finish; hard-kill/lease-recovery tests are still needed. |
| F-013 | P2 | Implemented in source | SQLite enables foreign keys, WAL, `busy_timeout=15000`, and `synchronous=NORMAL`; migration is additive. PostgreSQL runtime migration still needs a live service test. |
| F-014 | P2 | Implemented with regression coverage | Hybrid results retain keyword document IDs even when an embedding is null. |
| F-015 | P2 | Implemented in source with existing/new regression coverage | Wrapped line-item descriptions are accumulated and table scan is bounded to a 500-line window; arithmetic is still required before a parsed row is accepted. |
| F-016 | P2 | Implemented with limited confidence checks | EXIF orientation normalization, Tesseract OSD rotation when confident, image enhancement, OCR word confidence, and low-confidence review warnings are present. Deskew/rotation accuracy and noisy-currency behavior need image-corpus verification. |
| F-017 | P2 | Partially implemented | Explicit `Currency: XXX` is prioritized; financial-line symbols/codes are considered; supported-code validation includes a broader ISO code set. Currency extraction still requires a curated multi-currency test suite to prove it will not mistake item text such as “CAD workstation” for the invoice currency. |
| F-018 | P2 | Implemented baseline controls; production retest pending | Production docs/OpenAPI are disabled, health response does not expose environment, authenticated routes use sessions/CSRF, in-process API limits and Nginx rate limits are configured, and request/file/batch caps exist. Distributed rate limiting and chunked-body testing remain. |
| F-019 | P2 | Implemented in production templates; Docker runtime not verified here | Production backend image runs non-root, excludes pytest, uses multiple Uvicorn workers without reload; frontend builds static assets and serves via unprivileged Nginx; Compose has resource limits, read-only filesystems, dropped caps, and no-new-privileges. Ollama vendor image still has its upstream privilege model. Docker build/runtime tests pending. |
| F-020 | P2 | Partially implemented | Backend/Nginx security headers and CSP are configured; React renders values as text. Extracted source text may contain raw HTML in JSON by design to preserve evidence; any future export/email/HTML consumer must context-escape it. No browser XSS retest run. |
| F-021 | P2 | Implemented with regression coverage | Upload deduplication uses a tenant-scoped SHA-256 reservation table with a composite primary key (closing concurrent-upload races), does not reveal the existing document ID across owners, and preserves the explicit `allow_duplicate=true` option; deterministic `DocumentProcessingError` failures are not retried as transient failures. |
| F-022 | P2 | Implemented in source | Idle polling no longer re-runs semantic search; active document statuses are polled with lightweight status endpoints and paused for hidden tabs; stats endpoint counts across pages; list UI uses offset pagination; correction comparisons normalize empty values. Browser retest pending. |
| F-023 | P3 | Partially implemented | Canonical ISO `invoice_date_iso` is stored and indexed; only unambiguous normalized dates are range-filtered. Ambiguous slash dates remain for manual review rather than being guessed using an unconfigured locale. |
| F-024 | P3 | Implemented with filename helper | Unicode NFC normalization and suffix-preserving filename truncation are used; storage names remain generated UUIDs. Existing upload filename tests and a longer boundary regression should be run on Windows. |
| F-025 | P3 | Partially implemented / verification blocked | `fitz` import was replaced with `pymupdf`; pandas is constrained below 3 and production/dev requirements are separated. No frontend package lock or hashed Python lockfile was generated because dependency resolution was not available in this environment. Run npm/pip dependency scans in a network-enabled environment. |
| F-026 | P3 | Implemented in source | Four-card responsive KPI grid is present; reprocess reuses terminal job records; unique partial active-job index is added when existing records allow it; worker finalization checks `worker_id`. |
| F-027 | Info | Updated | README and checklist test counts and audit limitations have been updated to this remediation snapshot. |
| F-028 | Info | Not implemented / runtime blocked | Playwright click-through automation and a live PostgreSQL service matrix were not run or added. Add them to CI when a CI target and package lock are available. |

## Additional document-library deletion feature

- Added `DELETE /api/documents/{id}` and Delete actions in both the library rows and document review panel.
- The endpoint applies existing tenant/owner scoping, rejects documents with queued/running work (`409 Conflict`), stages the original file before committing database deletion, restores the file if the database transaction fails, and then removes its storage copy.
- The deletion removes extracted text/structured fields, embeddings, validation findings, processing jobs/events, and the SHA-256 duplicate reservation. This allows the same file content to be uploaded again after deletion.
- Regression tests cover complete file/data cleanup, duplicate reservation release, rejection of active documents, and reviewer ownership isolation.
- Deletion is permanent; there is no trash/restore or retention scheduler. SQLite connections use `PRAGMA secure_delete=ON` for deleted database pages, but this is not a forensic-erasure guarantee for WAL files, independent backups, filesystem snapshots or storage media. Public demo deletion is visible to every visitor in the shared demo workspace.

## Verification performed in this remediation workspace

- `cd backend && pytest -q`: **74 passed**.
- Deletion-specific regression cases also verify rollback restoration after a simulated database commit failure and that browser CORS preflight permits `DELETE` from the configured development frontend origin.
- `python -m compileall -q app tests scripts`: passed.
- Additive migration tested against a disposable copy of the supplied SQLite database: 23 document rows before and after; new columns/tables present; SQLite `foreign_keys=1`, `busy_timeout=15000`, `journal_mode=wal`.
- Integrity comparison: all 24 preserved database/storage items from the uploaded archive match their baseline SHA-256 and byte sizes.
- The tests include existing upload, worker, OCR, extraction, validation and API scenarios plus regression cases for authentication/session and CSRF, cross-tenant access, optimistic correction versioning, before/after history, first-admin one-time setup, duplicate workspace uploads, headerless CSV/XLSX, tax-ID/From/To extraction, wrapped table descriptions, hybrid results without embeddings, blank/low-similarity embedding behavior, manual override preservation, expired completed-job reconciliation, and document deletion cleanup/authorization.
- Python `compileall` is part of the final verification to be rerun when packaging.
- Original SQLite database and storage files are included from the supplied archive and are expected to remain byte-identical. Hash comparison is part of packaging verification.

## Tests not run in this environment

- Docker Compose build/start and service health checks.
- Frontend npm install, production build, `npm audit`, and Playwright/browser E2E.
- Production PostgreSQL migration/runtime and advisory-lock behavior.
- 25/30 concurrent upload deadlock reproduction after fix.
- 50/100/250/500/1,000 VU load test after fix.
- Post-fix 1,000-document ingestion and 10,000-row SQL performance benchmark.
- Live Ollama adversarial prompt-injection, extraction quality, and semantic ranking benchmark.
- `pip-audit`, Bandit, or container image scanning.

The project must not be described as production-ready or as supporting 1,000 concurrent users until those tests have been executed successfully on the target deployment hardware.
