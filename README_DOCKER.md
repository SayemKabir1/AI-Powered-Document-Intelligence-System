# Docker quick-start

Use the root `compose.yaml` for local development. Use `compose.prod.yaml` only after reading `docs/DEPLOYMENT_GUIDE.md` and setting production secrets.

## Local development

See `docs/RECRUITER_DEMO.md` for the no-login reviewer walkthrough and the shared-workspace warning.

```powershell
Copy-Item .\backend\.env.example .\backend\.env
docker compose config
docker compose up --build -d
docker compose ps
docker compose logs -f backend worker frontend
```

Open `http://localhost:5173`. The development Compose profile opens directly in Public demo mode with no login. Visitors share the same demo workspace and can upload/correct/reprocess documents. Use sample data only and do not expose the development stack directly to the Internet.

Enable Ollama by setting `OLLAMA_ENABLED=true` in `backend/.env`, then run:

```powershell
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull nomic-embed-text
docker compose restart backend worker
```

## Production template

Prepare a root `.env` from `.env.example`. Generate a unique `POSTGRES_PASSWORD`. For authenticated mode, also generate `SESSION_SECRET` and `BOOTSTRAP_TOKEN`. Set `CORS_ORIGINS` to the exact HTTPS origin. To create a no-login recruiter demo, set `DEMO_MODE=true`; visitors will share the same workspace, so deploy only sanitized sample data. Never put secrets in Vite variables or commit `.env`.

```powershell
Copy-Item .\.env.example .\.env
docker compose -f compose.prod.yaml config
docker compose -f compose.prod.yaml up --build -d
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs -f backend worker frontend db
```

The production frontend binds to loopback port 8080. Configure a trusted TLS reverse proxy in front of it before external use; the supplied Nginx container does not terminate TLS. In authenticated mode, complete one-time administrator setup with the bootstrap token. In Public demo mode, no login is required. See `docs/DEPLOYMENT_GUIDE.md` for backup, migration and operational cautions.

## Data safety

The local SQLite database is under `backend/` and uploaded files are under `backend/storage/` when running outside Compose. In Compose, Docker volume/mount mappings define the runtime locations. Never run `docker compose down -v`, `docker volume prune`, `docker system prune`, or destructive database resets unless you explicitly intend to destroy the relevant data. Back up both the database and uploaded storage before upgrading.
