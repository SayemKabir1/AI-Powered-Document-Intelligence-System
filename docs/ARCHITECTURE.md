# Architecture and design decisions

## Components

- **Frontend:** React + Vite workspace for upload, status, search, review, correction, reprocessing and cross-document comparison. The default recruiter/demo build opens directly in a shared public workspace; the optional authenticated build uses same-origin cookie sessions and CSRF headers. No shared secret is embedded in the bundle.
- **API:** FastAPI routes with Pydantic schemas. Production disables OpenAPI/Swagger routes.
- **Access modes:** `DEMO_MODE=true` disables login routes and uses one seeded shared demo administrator; all visitors share and can modify the workspace. `DEMO_MODE=false` enables local user accounts with PBKDF2 password hashes, HMAC-signed expiring HttpOnly sessions, CSRF double-submit tokens, tenant membership and admin/reviewer roles. This is not OIDC/SSO/MFA.
- **Database:** SQLAlchemy with SQLite WAL for local development and PostgreSQL configuration for production. Additive compatibility migrations preserve legacy document data. New records carry tenant/owner, optimistic version, normalized duplicate/date columns and manual overrides.
- **File storage:** Originals remain in private storage and use generated UUID filenames. Upload signature checks, file and aggregate size limits, concurrency limits and tenant-scoped SHA-256 deduplication are applied.
- **Worker:** Separate Python process consumes durable `processing_jobs`. Job claim and document status updates are atomic; final document/job completion is atomic and checks the current worker ID. Heartbeats and expired lease recovery prevent indefinite abandoned running jobs.
- **Document processing:** PyMuPDF extracts digital PDF text; Tesseract handles scanned PDF/image OCR; Pillow normalizes orientation and improves contrast. pandas/openpyxl/xlrd parse spreadsheets and detect headerless key/value layouts.
- **Extraction:** Deterministic label/rule extraction is the fallback. Optional local Ollama structured extraction is treated as untrusted; prompt-like content and conflicting values require manual review. Evidence and arithmetic validation remain separate from model output.
- **Search:** Keyword filters use SQL expressions. Semantic/hybrid queries create embeddings outside DB sessions, project ID/vector values only, apply a minimum similarity threshold, and union keyword-only hits. The current vector ranking remains in-process Python cosine over bounded JSON vectors, not pgvector.
- **Validation:** Missing data/evidence, ambiguous dates, unsupported currencies, arithmetic mismatches, incomplete line items and possible duplicates create warnings/errors. Cross-document comparison will not claim a match when core invoice identity is missing.

## Processing flow

1. In authenticated mode, the browser signs in and receives a session and CSRF token. In Public demo mode, it opens directly into the shared demo workspace without a session.
2. A tenant/owner-scoped upload is validated for extension, signature, per-file size, total request size and duplicate hash.
3. Original document metadata, upload event and a durable queue job are committed.
4. Worker claims a queued job and sets the document to processing in the same transaction.
5. OCR/text/spreadsheet parsing and optional Ollama extraction run outside an open SQL session.
6. Rules, LLM grounding, evidence and financial validation are combined. Unsupported or uncertain values remain nullable or receive manual-review warnings.
7. Document result and job completion are committed atomically with worker ownership checks.
8. The UI polls lightweight status endpoints while jobs are active. Idle tabs do not periodically rerun semantic searches.
9. Corrections are saved with expected version, source/evidence recalculation and a before/after event snapshot. Reprocessing preserves explicit manual overrides.

## Deployment profiles

- Root `compose.yaml`: development only (SQLite, Vite dev server, reload mode, loopback host ports).
- `compose.prod.yaml`: production starting template (PostgreSQL, non-root backend/worker, static Nginx, resource and filesystem restrictions). It is loopback-bound and requires an external TLS reverse proxy before network exposure.

## Operational notes

- Do not treat the SQL job queue as a horizontally scalable broker. For higher throughput, add a dedicated queue/broker, shared object storage and isolated parser worker pool.
- Do not treat JSON-vector cosine ranking as a production vector index. Use pgvector or a dedicated vector service when data volume warrants it.
- The previous Antigravity audit measured a 25-user mixed-workload ceiling and broke at 50. No post-remediation concurrency capacity is claimed until the full isolated load ramp is repeated.
- OCR and LLM output can be wrong. Financial extraction must remain reviewable by a human.
