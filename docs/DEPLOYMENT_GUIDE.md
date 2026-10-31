# Deployment and local verification guide

## Development stack

The root `compose.yaml` is a development configuration. It uses SQLite, Vite dev server, reload mode, and loopback-bound host ports. It is intended for local development only.

```powershell
Copy-Item .\backend\.env.example .\backend\.env
docker compose config
docker compose up --build -d
docker compose ps
docker compose logs -f backend worker frontend
```

Open `http://localhost:5173`. The supplied development Compose profile has `DEMO_MODE=true`, so it opens without a login. Visitors share the same workspace and can upload, process, correct, reprocess and compare. Use only sample files and do not expose this development stack directly to the Internet. For local Ollama, pull `qwen2.5:3b` and `nomic-embed-text` inside the `ollama` service and restart `backend` and `worker` after changing model settings.

## Production Compose template

`compose.prod.yaml` is a hardened starting template, not a finished Internet deployment. It uses PostgreSQL, a persistent app-storage volume, a production backend image, a worker, Ollama, and an unprivileged Nginx static frontend. Host port 8080 is bound to `127.0.0.1` deliberately.

### 1. Prepare production secrets

Copy the template and generate the database password. The password is hex-encoded so it is safe inside the SQLAlchemy URL without URL escaping. Set `DEMO_MODE=true` only for a public recruiter demo using sanitized sample data; all visitors then share one writable workspace and no login is required. Leave `DEMO_MODE=false` for authenticated/private use.

```powershell
Copy-Item .\.env.example .\.env
$env:POSTGRES_PASSWORD = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$env:SESSION_SECRET = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
$env:BOOTSTRAP_TOKEN = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
Write-Output "POSTGRES_PASSWORD=$env:POSTGRES_PASSWORD"
Write-Output "SESSION_SECRET=$env:SESSION_SECRET"
Write-Output "BOOTSTRAP_TOKEN=$env:BOOTSTRAP_TOKEN"
Write-Output "DEMO_MODE=false"
```

Paste these values into the root `.env` file. Do not publish them or place them in frontend variables. Set `CORS_ORIGINS` to the exact trusted HTTPS origin. Keep `.env` out of Git and support tickets.

### 2. Add TLS termination

The Compose frontend serves HTTP on `127.0.0.1:8080`; it does not terminate TLS. Put a trusted TLS reverse proxy (for example, a managed ingress or host-level Nginx/Caddy) in front of it. Only allow the intended external hostname, redirect HTTP to HTTPS, and ensure the outer proxy correctly forwards client IP and scheme. Any publicly shared deployment should use HTTPS. Secure session cookies additionally require HTTPS when authenticated mode is enabled; HSTS is enabled for the production profile.

### 3. Build and start

```powershell
docker compose -f compose.prod.yaml config
docker compose -f compose.prod.yaml up --build -d
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs -f backend worker frontend db
```

Pull local models if Ollama is enabled:

```powershell
docker compose -f compose.prod.yaml exec ollama ollama pull qwen2.5:3b
docker compose -f compose.prod.yaml exec ollama ollama pull nomic-embed-text
```

In authenticated mode, complete the one-time administrator setup in the UI using the `BOOTSTRAP_TOKEN`. Remove/rotate the bootstrap token after initial setup and restart the services. Do not put the bootstrap token into a browser build or share it with reviewers. In Public demo mode, the app seeds a dedicated shared demo identity and opens without a password; visitors can see and modify all documents in that workspace.

### 4. Backups and migrations

The application uses additive compatibility migrations for legacy document/job/event columns and does not intentionally drop tables or rows. Before production upgrade:

1. Stop traffic and ensure no document job is running.
2. Take a PostgreSQL logical backup and a consistent backup of the `app_storage` volume.
3. Record row counts and storage file hashes.
4. Restore both backups to a staging instance and run the upgrade there.
5. Verify login, document access, processing, history, corrections, and search.
6. Only then upgrade production.

Never use `docker compose down -v`, `docker volume prune`, `docker system prune`, or destructive SQL as a routine upgrade step. The application supports explicit permanent deletion of individual documents from the library; it does not provide a recycle bin, restore workflow, or automatic retention deletion. Take and test backups according to your retention policy before deleting records.

### 5. Operational limits and caveats

- The in-process Python rate limiter is per backend process; the Nginx rate limit protects the single frontend gateway. Multi-replica deployments need a shared/distributed rate limiter.
- Search vectors remain JSON blobs scored in Python, not pgvector. A 10,000-document limit is enforced for candidate collection. Use an indexed vector extension/service before larger collections.
- Four Uvicorn workers are configured in the production image; verify concurrent DB sessions, migration/startup behavior, and resource use under the actual Compose profile before scaling replicas.
- The default production Compose resource caps are starting values, not sizing recommendations. Benchmark on the real host and tune with measured results.
- Authenticated mode includes local password accounts, role and tenant scoping, and signed sessions. It does not include OIDC/SSO/MFA, password recovery, email verification, or formal identity lifecycle controls. Public demo mode deliberately disables identity checks and is only suitable for a sanitized, shared demo workspace.
- No post-remediation 50+ VU test has been run. Do not infer that the earlier 25-VU measured limit has improved until a repeat load test passes.
