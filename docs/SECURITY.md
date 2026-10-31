# Security model, controls, and residual risks

## Scope

This document describes the remediation code in this archive. It is not a penetration-test certificate, compliance statement, or guarantee that the application is safe for Internet exposure. Antigravity previously reported 28 findings, including critical upload availability, authentication/IDOR, and worker consistency defects. The source has been changed to address the core code paths, but post-fix live Docker/security/load retests remain outstanding.

## Identity and access model

The application has two mutually exclusive modes, controlled by `DEMO_MODE`.

- **Public demo (`DEMO_MODE=true`):** authentication routes are not mounted, API requests use one dedicated `public-demo@local.invalid` administrator identity, and no password is requested. All visitors share one workspace and can read and modify its documents, including uploads, corrections, reprocessing and comparisons. This is intended only for sanitized synthetic/sample data. Do not use it for private or production documents.
- **Authenticated (`DEMO_MODE=false`):** the first-run setup flow creates a workspace (tenant) and administrator. Production first-run setup requires a bootstrap token.
- Passwords are hashed with PBKDF2-HMAC-SHA256 and per-password random salts.
- Login issues a signed, expiring server-side-verifiable session cookie (`HttpOnly`, `SameSite=Strict`; `Secure` outside development) and a separate CSRF cookie/header pair.
- In authenticated mode, API reads and writes require the signed session; non-safe HTTP methods validate the CSRF token. In public demo mode, no session or CSRF token is required because the workspace is intentionally shared and public.
- Documents carry tenant and owner identifiers. Reviewers are scoped to their own documents; administrators are scoped to their workspace.
- Admin user-management routes are administrator-only.
- Corrections require an expected document version; stale writes return `409 Conflict`.
- Reprocess/manual correction events retain before/after or previous-state snapshots.

This is a local account/session mechanism, not OIDC/SSO, MFA, password recovery, email verification, session revocation, or an enterprise identity lifecycle. It needs independent security review before a shared organizational deployment.

## Defensive controls present in source

| Area | Implemented controls | Remaining concerns |
|---|---|---|
| Upload/storage | Extension allowlist, magic signatures, generated UUID storage name, NFC filename normalization, suffix-preserving display name, per-file and aggregate limits, maximum file count, bounded upload slots, workspace SHA-256 deduplication, private storage | Repeat path traversal and high-concurrency tests against Docker; chunked requests without Content-Length rely on per-file and aggregate route checks; no malware scanner |
| Database | SQLAlchemy parameterized ORM expressions, tenant scoping, indexed duplicate checks, optimistic versioning, SQLite foreign keys/WAL/busy timeout | PostgreSQL runtime, migration rehearsal, distributed concurrency and load retest pending |
| Worker | Atomic claim/finalization, worker ownership checks, bounded retries, parser errors classified as non-retryable, heartbeat, 120-second lease, SIGTERM/SIGINT stops new work | Hard-kill during active OCR and simultaneous worker tests pending; in-flight task is allowed to complete during graceful shutdown |
| AI safety | Document text is treated as untrusted, detected prompt-override text bypasses Ollama, conflicting rule/model financial fields require review, unsupported values are grounded or nulled | Pattern detection is not a universal prompt-injection defense; perform live adversarial-model testing; human review remains mandatory |
| Search | Ollama call occurs outside DB session; projected vector data; minimum similarity; blank documents skipped; hybrid retains keyword-only records | Local Python vector ranking is not a scalable vector index; quality/latency benchmark pending |
| HTTP | Production OpenAPI/docs disabled; minimal health output; rate-limit middleware; CORS allowlist; CSRF; CSP and security headers | Rate limiter is in-process; multi-replica deployments require a shared gateway/limiter; confirm outer TLS and proxy trust settings |
| Containers | Production backend/worker run non-root, no-new-privileges, dropped Linux capabilities, read-only root FS, tmpfs, resource limits; static frontend uses unprivileged Nginx | Docker images and Compose runtime were not built/launched in this editing environment; Ollama uses the upstream image's default user/privileges |
| Dependencies | Production/dev Python requirements separated; PyMuPDF import modernized; pandas constrained below 3; dependency minimums raised | `package-lock.json`, hashed Python lock, `npm audit`, `pip-audit`, Bandit and image scans not completed |

## Sensitive information and document handling

- `VITE_API_KEY` is not used by the frontend. Browser bundles must never contain reusable API or bootstrap secrets.
- The source preserves extracted text as evidence. JSON responses may therefore contain literal angle-bracket/script-like text. React renders values as text and does not use unsafe HTML DOM sinks, but any future HTML, email, PDF, or export consumer must apply context-appropriate output encoding. Do not render extracted text using `dangerouslySetInnerHTML`.
- The application provides permanent per-document deletion, including the original stored file and associated database/search/history records. SQLite connections enable `secure_delete=ON` for deleted database pages, but that does not guarantee forensic erasure from WAL files, backups, filesystem snapshots, or underlying media. The app does not provide a recycle bin, restore, scheduled retention policy, legal hold, or encrypted backup orchestration. Protect database/storage volumes and backups at the host/platform layer; a deleted file may still exist in independent backups.
- Never upload real customer financial documents into unapproved hosted services. Ollama is configured as a local model service in the supplied Compose profiles.

## Required security verification before deployment

For a recruiter-facing public demo, set `DEMO_MODE=true` in both the backend environment and frontend build argument (the supplied Compose files pass the same variable to both). Deploy only sanitized sample documents and clearly disclose that visitors share and can change the same workspace. Public demo mode is not a security boundary and must not be used for confidential data. Keep HTTPS termination, an explicit CORS allowlist, upload limits, rate limits and resource controls in place.

1. Run the isolated security fixtures from Antigravity again against the post-fix container stack.
2. Verify user B receives `404` for user A's document result, history, correction, and reprocess routes; verify workspace admin access is restricted to that tenant.
3. Verify API responses, browser bundle, source maps, logs, and image layers contain no `.env`, API key, database password, session secret, or bootstrap token.
4. Test CSRF rejection for a missing/wrong token and session rejection after expiry/deactivation.
5. Run upload traversal, MIME/signature mismatch, 50 MB single-file, 100 MB request, corrupt archive, oversized page/frame/sheet, and concurrent upload tests.
6. Run live LLM prompt/label spoofing tests and inspect field-level review warnings.
7. Run `pip-audit`, `npm audit`, Bandit, and container image scans against resolved, locked dependencies.
8. Validate TLS termination, secure cookies, HSTS, proxy client IP behavior, API rate limits, and disabled production docs/OpenAPI.
9. Re-run the 25- and 50-VU mixed and concurrent-upload tests. Do not increase concurrency until the lower stage is stable.

## Residual deployment verdict

The remediation closes significant code-level gaps but **does not authorize network-exposed production deployment yet**. Post-fix Docker build/runtime, PostgreSQL migration, browser E2E, dependency scans, real adversarial LLM testing, and concurrency retests remain required. See `AUDIT_REMEDIATION_MATRIX.md` for finding-by-finding status.
