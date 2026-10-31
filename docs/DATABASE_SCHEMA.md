# Database schema and migration notes

## Current logical tables

### `tenants`
Workspace identity (`id`, `name`, `created_at`).

### `users`
Workspace user (`id`, `tenant_id`, normalized unique `email`, `password_hash`, `role`, `is_active`, `created_at`). Roles currently supported: `admin` and `reviewer`.

### `system_setup_state`
Singleton setup flag used to make first-administrator creation one-time under concurrent requests.

### `documents`
- Identity and file metadata: `id`, `original_filename`, `stored_filename`, `file_type`, `mime_type`, `file_size`, `sha256`.
- Access scope: `tenant_id`, `owner_id`.
- Concurrency/manual review: `version`, `manual_overrides`.
- Search/duplicate fields: `invoice_date_iso`, `invoice_number_norm`, `supplier_name_norm`.
- Pipeline fields: `status`, `page_count`, `extracted_text`, `extracted_data`, `field_evidence`, `embedding`, `validation_errors`, `validation_warnings`, `extraction_method`, `processing_error`, `created_at`, `updated_at`.

### `processing_jobs`
Durable queue row (`id`, `document_id`, `status`, `attempt_count`, `max_attempts`, `available_at`, `locked_at`, `started_at`, `finished_at`, `worker_id`, `last_error`, timestamps). Indexes cover ready-job polling and document history. A partial unique active-job index is added when the existing data contains no conflicting active duplicate rows.

### `processing_events`
Append-oriented event/history rows (`id`, `document_id`, `event_type`, `message`, `details`, `created_at`). `details` can hold correction before/after snapshots and reprocess snapshots.

## Important indexes

- Document status, SHA-256, tenant, owner and created-at ordering.
- Canonical invoice date.
- Composite duplicate lookup `(tenant_id, status, invoice_number_norm, supplier_name_norm)`.
- Processing-job ready queue `(status, available_at, created_at)`.
- Processing-job document history `(document_id, created_at)`.

## Migration and preservation behavior

`Base.metadata.create_all` creates missing new tables. `run_compatibility_migrations` adds missing document/job/event columns and indexes and backfills unambiguous ISO dates and normalized invoice/supplier fields. It does not drop tables, rows, files or storage directories.

Legacy document rows initially have null tenant/owner columns. The first administrator setup assigns those rows to the first workspace without deleting or rewriting their extracted invoice data or original file contents. Back up the database and storage directory before deploying this upgrade. Verify the migration on a copy first.

For production PostgreSQL, run a staging migration rehearsal and review locking/startup behavior with the configured Uvicorn worker count. The application currently uses compatibility migrations rather than a full Alembic revision history; adding Alembic-managed migrations is recommended before a long-lived production rollout.
