# Recruiter demo access

## Local reviewer access (no account required)

The supplied development Compose profile starts with `DEMO_MODE=true` and `VITE_DEMO_MODE=true`. A recruiter does not need an email, password, bootstrap token, or administrator account.

From the project root:

```powershell
docker compose up --build -d
docker compose ps
```

Open:

- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8000/health`

The UI should open directly to **Document Intelligence** and show **Public demo · shared workspace**. The demo identity is seeded automatically when the backend starts. The seed step preserves existing document rows and files; it adds a demo user/workspace and assigns only legacy rows that have no tenant association.

## What reviewers can try

Use the included `sampleData/` files to upload PDF, JPG, PNG, TIFF, XLSX, XLS, and CSV examples. Reviewers can inspect extracted invoice fields, source text/evidence, processing status and validation findings; search with keyword, semantic or hybrid mode; apply filters; compare completed documents; correct fields; and reprocess failed or completed documents. Each library row and the document review panel also provide a **Delete** action for removing an old document.

Deletion is permanent. It removes the original stored file together with extracted text and fields, embeddings, validation findings, duplicate-upload reservation, processing jobs, and processing history. A confirmation prompt appears before deletion. Queued or processing documents cannot be deleted until their worker activity has finished. There is no trash/recovery feature.

## Important shared-workspace behaviour

This is deliberately a public, writable demo—not a private multi-user workspace. Every visitor sees the same demo tenant. Visitors can upload files, change extracted values, reprocess records, and see each other's changes. Do not upload personal, confidential, customer, financial, or production documents. Do not deploy this demo using a database or storage volume that contains private records.

For a hosted recruiter URL, use a separate sanitized copy of the project, set `DEMO_MODE=true` in the root `.env`, build the frontend with the same setting (the supplied production Compose file passes this setting into the Vite build), and place the app behind HTTPS and a trusted reverse proxy. The production template still needs its database password, explicit `CORS_ORIGINS`, backups, resource limits and operational verification. Public demo mode removes login, not the need to protect the host and manage abuse.

## Disable public demo mode

For private use, set `DEMO_MODE=false` and use the authenticated first-admin setup. The frontend build must also use `VITE_DEMO_MODE=false`. Restart/rebuild both backend and frontend so the two settings match. Do not mix a public frontend with an authenticated backend or vice versa.

To stop the local development containers without deleting their persistent data:

```powershell
docker compose down
```

Do not add `-v` unless you intentionally want to delete named Docker volumes.
