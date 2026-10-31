# Engineering remediation review report

**Project:** AI-Powered Document Intelligence System
**Review basis:** Latest supplied ZIP and the seven Antigravity audit artifacts dated 30 October 2026
**Remediation mode:** Work on an isolated copy; original archive and user-local project were not edited

## Executive summary

The latest source archive was reviewed against Antigravity findings F-001 through F-028. Core code paths have been changed for upload concurrency, server-side session authentication and tenant scoping, worker transaction integrity, search performance, indexed duplicate checks, extraction correctness, prompt-risk review warnings, optimistic correction concurrency, database integrity, frontend polling, and container deployment separation.

The backend suite in the remediation workspace now reports **74 passed**. This provides regression evidence for the code paths covered by the suite. It does not prove the production container build, PostgreSQL deployment, live browser workflow, high-concurrency behavior, dependency scan, or security posture under real network exposure.

**Deployment verdict: NOT READY for public or multi-user organizational production until the post-fix runtime and security/load tests are completed.** The old audit measured only 25 sustainable mixed read-heavy users and failed at 50. No new capacity figure is claimed because the changes were not load-tested in Docker after remediation.

## Significant changes

1. **Authentication and isolation:** Added local accounts, PBKDF2 password hashes, HMAC-signed HttpOnly session cookies, CSRF double-submit validation, tenant/owner document scope, administrator role checks, one-time bootstrap setup, and a user-management API. Browser API-key exposure removed.
2. **Upload safety:** Upload handler is synchronous, upload concurrency and aggregate request size are bounded, content signatures are checked, SHA-256 duplicates are rejected workspace-wide without exposing the existing record ID, and stored filenames remain UUID-based.
3. **Worker reliability:** Job claiming and document processing status transition together; final document/job completion is atomic and worker-owned; completed documents are reconciled after an expired lease; parser errors are not retried as transient errors; lease timeout reduced.
4. **Search and database:** Added SQLite foreign-key/WAL/busy-timeout configuration, additive schema migrations, normalized indexed duplicate/date columns, projected list/search queries, released DB connections before Ollama/vector ranking, minimum similarity, and hybrid keyword/vector union.
5. **Extraction and review:** Added label specificity, tax-ID and subtotal exclusions, headerless CSV/XLSX handling, wrapped table descriptions, currency validation and prompt/rule conflict warnings, blank-document embedding avoidance, and line-item grounding boundaries.
6. **Manual correction:** Added optimistic document versions, expected-version checks, manual override persistence through reprocessing, and before/after snapshots.
7. **Frontend and deployment:** Removed 3.5-second full-search polling, introduced light status polling and a stats endpoint, offset pagination, four-column KPI layout, a non-root static Nginx production frontend, and hardened production backend/worker Dockerfiles/Compose.

## Automated verification

- Backend suite: **74 passed** in the remediation workspace.
- Existing behavior tests were preserved and additional regression tests were added for the remediation areas listed above.
- The application’s supplied historical evaluation result files were not overwritten or presented as post-fix benchmarks.
- The supplied SQLite database and uploaded storage files are preserved byte-for-byte in the deliverable (24/24 baseline items matched). The additive migration was tested against a separate disposable copy: 23 document rows remained 23, all additive columns/tables were present, and SQLite foreign keys, WAL, and a 15-second busy timeout were active. The actual included database was not migrated.

## Outstanding items

- Rebuild and start both development and production Docker Compose stacks.
- Repeat the Antigravity upload deadlock reproduction at 25/30 parallel uploads and confirm `/health` remains responsive.
- Re-run the mixed API ramp at 1, 5, 10, 25 and 50 VUs; escalate only when the 50-VU stage passes stop conditions. Do not assume 1,000-user support.
- Verify the 1,000-invoice ingestion, 10,000-row database benchmarks, cross-tenant IDOR checks, worker kill/restart, live Ollama adversarial prompts, and OCR/semantic search quality.
- Run the frontend production build, Playwright smoke tests, npm/pip dependency audits, Bandit, and image scanning.
- Generate a frontend package lock and reproducible Python hash lock once dependency resolution is available.
- Enterprise identity controls (OIDC/SSO/MFA/password recovery), encryption/retention, distributed rate limiting, and pgvector remain future production architecture work.

See `AUDIT_REMEDIATION_MATRIX.md` for the per-finding status and `DEPLOYMENT_GUIDE.md` for safe local/production setup.
