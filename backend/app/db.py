import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

connect_args = {"check_same_thread": False, "timeout": 15} if settings.database_url.startswith("sqlite") else {}
engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if not settings.database_url.startswith("sqlite"):
    engine_options["pool_timeout"] = 15
engine = create_engine(settings.database_url, **engine_options)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA secure_delete=ON")
        finally:
            cursor.close()

    # WAL is a persistent database setting. Set it once during engine setup
    # rather than trying to change journal mode every time a pool connection is
    # opened (which can itself contend with active transactions). In-memory
    # SQLite databases report `memory` and are intentionally left unchanged.
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    except Exception:
        logging.getLogger(__name__).exception("Unable to enable SQLite WAL journal mode")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_compatibility_migrations(bind=engine) -> None:
    """Additive-only migrations for installations created before tenant/review metadata.

    No existing rows, files, or tables are dropped. New columns are nullable or have
    safe defaults so this can run against the existing local SQLite database.
    """
    inspector = inspect(bind)
    if "documents" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("documents")}
    additions = {
        "tenant_id": "VARCHAR(36)",
        "owner_id": "VARCHAR(36)",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "manual_overrides": "JSON",
        "ocr_confidence": "FLOAT",
        "invoice_date_iso": "VARCHAR(10)",
        "invoice_number_norm": "VARCHAR(100)",
        "supplier_name_norm": "VARCHAR(200)",
    }
    job_columns = {column["name"] for column in inspector.get_columns("processing_jobs")} if "processing_jobs" in inspector.get_table_names() else set()
    event_columns = {column["name"] for column in inspector.get_columns("processing_events")} if "processing_events" in inspector.get_table_names() else set()
    with bind.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE documents ADD COLUMN {name} {definition}"))
        if "processing_jobs" in inspector.get_table_names() and "finished_at" not in job_columns:
            timestamp_type = "DATETIME" if bind.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE"
            connection.execute(text(f"ALTER TABLE processing_jobs ADD COLUMN finished_at {timestamp_type}"))
        if "processing_events" in inspector.get_table_names() and "details" not in event_columns:
            connection.execute(text("ALTER TABLE processing_events ADD COLUMN details JSON"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON documents (tenant_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_owner_id ON documents (owner_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_invoice_date_iso ON documents (invoice_date_iso)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_created_at_desc ON documents (created_at DESC)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_duplicate_lookup ON documents (tenant_id, status, invoice_number_norm, supplier_name_norm)"))
        if bind.dialect.name == "sqlite":
            # Preserve the existing database and only backfill values that have
            # an unambiguous canonical ISO representation.
            connection.execute(text("UPDATE documents SET invoice_date_iso=json_extract(extracted_data, '$.invoice_date') WHERE invoice_date_iso IS NULL AND json_valid(extracted_data) AND json_extract(extracted_data, '$.invoice_date') GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"))
            connection.execute(text("UPDATE documents SET invoice_number_norm=lower(trim(json_extract(extracted_data, '$.invoice_number'))) WHERE invoice_number_norm IS NULL AND json_valid(extracted_data) AND json_extract(extracted_data, '$.invoice_number') IS NOT NULL"))
            connection.execute(text("UPDATE documents SET supplier_name_norm=lower(trim(json_extract(extracted_data, '$.supplier_name'))) WHERE supplier_name_norm IS NULL AND json_valid(extracted_data) AND json_extract(extracted_data, '$.supplier_name') IS NOT NULL"))
        else:
            connection.execute(text("UPDATE documents SET invoice_date_iso=extracted_data->>'invoice_date' WHERE invoice_date_iso IS NULL AND extracted_data->>'invoice_date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"))
            connection.execute(text("UPDATE documents SET invoice_number_norm=lower(trim(extracted_data->>'invoice_number')) WHERE invoice_number_norm IS NULL AND extracted_data->>'invoice_number' IS NOT NULL"))
            connection.execute(text("UPDATE documents SET supplier_name_norm=lower(trim(extracted_data->>'supplier_name')) WHERE supplier_name_norm IS NULL AND extracted_data->>'supplier_name' IS NOT NULL"))
        # Do not make startup fail on legacy databases that already contain
        # multiple active jobs. Install this guard only when their data allows it.
        if "processing_jobs" in inspector.get_table_names():
            active_duplicates = connection.execute(text(
                "SELECT 1 FROM processing_jobs WHERE status IN ('queued','running') "
                "GROUP BY document_id HAVING COUNT(*) > 1 LIMIT 1"
            )).first()
            if not active_duplicates:
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_processing_jobs_one_active_per_document ON processing_jobs(document_id) WHERE status IN ('queued','running')"))
        # Backfill one workspace/hash reservation per existing duplicate set.
        # Existing duplicate document rows are preserved; this only prevents new ones.
        if "document_hashes" in inspector.get_table_names() and "tenants" in inspector.get_table_names():
            connection.execute(text(
                "INSERT INTO document_hashes (tenant_id, sha256, document_id, created_at) "
                "SELECT tenant_id, sha256, MIN(id), CURRENT_TIMESTAMP FROM documents "
                "WHERE tenant_id IS NOT NULL GROUP BY tenant_id, sha256 "
                "ON CONFLICT (tenant_id, sha256) DO NOTHING"
            ))
