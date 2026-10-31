# Project checklist and remediation status

Legend: `[x]` implemented and covered by code/test evidence in this workspace; `[~]` implemented or partly verified with remaining runtime/scale limitations; `[ ]` not implemented or not yet verified.

## Task 1: Document processing and OCR
- [x] PDF, JPG/JPEG, PNG, TIFF, XLSX, XLS and CSV format dispatch.
- [x] Digital PDF text extraction page-by-page and scanned PDF/image OCR through Tesseract.
- [x] Multi-frame TIFF and multi-sheet spreadsheet handling with page/sheet/row/pixel/archive limits.
- [x] OCR preprocessing: EXIF normalization, orientation detection/rotation when OSD confidence is sufficient, contrast/sharpening, and OCR confidence warnings.
- [x] Corrupt/unsupported inputs become document-level failures without terminating the entire batch.
- [~] OCR degradation and orientation accuracy need a fresh controlled multi-format corpus test; poor-quality scans must remain subject to human review.
- [~] 1,000-page digital-text PDF performance is not a 1,000-page scanned OCR benchmark.

## Task 2: AI extraction
- [x] Structured invoice schema and conservative rule-based extraction fallback.
- [x] Optional Ollama extraction and local embeddings; no hosted paid inference API required.
- [x] Source-grounding and line-item numeric evidence checks.
- [x] Prompt override and conflicting source-label warnings; unsafe prompt-like content bypasses Ollama.
- [x] Rule regressions for generic From/To prose, Tax IDs, subtotal/total distinction, wrapped descriptions, and headerless key-value spreadsheets.
- [~] Prompt-injection pattern detection is defense-in-depth, not a complete guarantee against all in-band document prompt attacks.
- [~] Live Ollama adversarial testing and broader real-world field precision/recall evaluation remain outstanding.

## Task 3: Validation and cross-document verification
- [x] Missing-field, source-evidence, ambiguity, unsupported-currency, arithmetic, line-item and duplicate warnings/errors.
- [x] Comparison refuses to claim a match when core identity fields are missing.
- [x] Line items compare in normalized order rather than only raw positional order.
- [~] Row-level alignment across arbitrary invoice layouts is not a full accounting reconciliation engine.

## Task 4: API and worker
- [x] Authenticated upload, result, history, status, correction, reprocess, comparison and search APIs.
- [x] Synchronous upload handler, concurrency semaphore, file/aggregate request caps, format signatures and workspace SHA-256 deduplication.
- [x] Durable SQL job queue with atomic claim/final state, worker ownership guard, retry classification, heartbeats and expired-lease reconciliation.
- [x] Non-retryable parser/document errors do not waste transient retry attempts.
- [~] Live Docker deadlock retest, SIGTERM/hard-kill recovery and concurrent multi-worker testing remain outstanding.

## Task 5: Database and search
- [x] SQLite foreign keys, WAL, busy timeout and additive-only compatibility migration.
- [x] Tenant/owner metadata, optimistic version column, manual override JSON and processing-event snapshots.
- [x] Indexed normalized invoice/supplier/date columns and scalar duplicate queries.
- [x] Keyword filters, canonical ISO date range fields, metadata-only result projections and paginated results.
- [x] Semantic search uses query/document prefixes, blank-content suppression and a configurable similarity floor.
- [x] Hybrid ranking preserves keyword-only results when embeddings are missing.
- [x] Workspace-scoped document statistics endpoint.
- [~] Search ranking still uses Python cosine scoring over projected JSON vectors; pgvector or a dedicated vector service is needed at larger scale.
- [~] PostgreSQL runtime and 10,000-row / semantic latency benchmarks have not been rerun after the changes.

## Task 6: Frontend and deployment
- [x] Login/first-admin UI, session-aware API calls, CSRF header, sign-out and correction version propagation.
- [x] Search mode/filters, offset pagination, status-only polling while active, hidden-tab polling pause, and stats separate from the current page.
- [x] Four-card responsive KPI grid.
- [x] Separate development and production Dockerfiles/Compose profiles.
- [x] Non-root production backend and Nginx frontend, resource limits, capability drop, read-only filesystem and security headers.
- [~] Full Vite production build and browser/Playwright run unavailable in this workspace.
- [~] Docker images and Compose profiles need an actual Docker Desktop build/start test on the target machine.

## Task 7: Testing and evaluation
- [x] Backend regression suite: **74 passed** in the remediation workspace.
- [x] Added targeted tests for authentication, CSRF, access scoping, one-time setup, versioned corrections, snapshots, duplicate uploads, worker lease reconciliation, search union, extraction parsing, and override persistence.
- [~] Supplied historic evaluation JSON files were not overwritten; new post-fix real-world/multi-format benchmark results have not been generated.
- [~] Post-fix 25/50 VU concurrency and 25/30 concurrent upload tests have not been run.
- [~] Dependency audits, frontend production build, browser E2E and PostgreSQL integration remain unverified.

## Security, operations and delivery
- [x] Server-side signed sessions and CSRF; tenant/owner authorization; API key removed from browser bundle.
- [x] Production docs/OpenAPI disabled; environment string removed from health output; rate limits and security headers added.
- [~] No OIDC/SSO/MFA, password recovery, email verification, or application-level encryption/retention controls.
- [~] `frontend/package-lock.json` and hashed Python lockfile not generated in the offline editing environment.
- [~] Playwright CI and PostgreSQL service matrix are not implemented.
- [x] Audit remediation matrix, security model, deployment guide, and current verification caveats documented.
- [ ] Walkthrough video and GitHub publication are manual delivery items.

## Data preservation
- [x] The supplied project ZIP and user's Windows local source were not modified by the editing process.
- [x] Existing SQLite database and `backend/storage` files are preserved in the corrected archive and are hash-checked before packaging.
- [x] Additive migrations are used; no application code path introduced a database drop/reset or storage cleanup.
- [~] Run migration against a backup copy on Windows and verify row counts/storage hashes before using the corrected code against the user's existing local database.
