from __future__ import annotations

import hashlib
import re
import uuid
import io
import zipfile
import unicodedata
from threading import BoundedSemaphore
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import Text, cast, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session, load_only
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import settings
from app.core.auth import get_current_user, document_scope
from app.db import get_db
from app.models import Document, DocumentHash, ProcessingEvent, ProcessingJob, User
from app.schemas import (
    CompareRequest,
    CompareResult,
    CorrectionRequest,
    DocumentResponse,
    DocumentResultResponse,
    InvoiceData,
    ProcessingStatusResponse,
    UploadResponse,
)
from app.services.document_processor import SUPPORTED_EXTENSIONS
from app.services.evidence import collect_field_evidence
from app.services.extractor import create_embedding
from app.services.jobs import add_event, enqueue_document_job
from app.services.validation import compare_invoice_data, validate_invoice

router = APIRouter(prefix="/api")
MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024
MAX_UPLOAD_REQUEST_BYTES = settings.upload_request_mb * 1024 * 1024
_UPLOAD_SLOTS = BoundedSemaphore(max(1, settings.upload_concurrency))


def _safe_original_name(name: str | None) -> str:
    raw = unicodedata.normalize("NFC", (name or "unnamed").replace("\\", "/").split("/")[-1])
    suffix = Path(raw).suffix[:20]
    stem = raw[:-len(suffix)] if suffix else raw
    chars = []
    for char in stem:
        category = unicodedata.category(char)
        if category[0] in {"L", "N"} or char in " ._()-":
            chars.append(char)
        elif category[0] == "C":
            continue
        else:
            chars.append("_")
    clean_stem = "".join(chars).strip(" .") or "unnamed"
    max_stem = max(1, 255 - len(suffix))
    clean_stem = clean_stem[:max_stem].rstrip(" .") or "unnamed"
    return f"{clean_stem}{suffix}"[:255]


def _check_signature(extension: str, content: bytes) -> None:
    if not content:
        raise ValueError("File is empty")
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("PDF signature is invalid")
    if extension in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
        raise ValueError("JPEG signature is invalid")
    if extension == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG signature is invalid")
    if extension in {".tif", ".tiff"} and not content.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")):
        raise ValueError("TIFF signature is invalid")
    if extension == ".xlsx":
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise ValueError("XLSX must be a valid ZIP-based workbook")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as workbook:
                entries = workbook.infolist()
                names = {entry.filename for entry in entries}
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise ValueError("ZIP file is not a valid XLSX workbook")
                if len(entries) > 10_000:
                    raise ValueError("XLSX contains too many archive entries")
                uncompressed_size = sum(entry.file_size for entry in entries)
                if uncompressed_size > 300 * 1024 * 1024:
                    raise ValueError("XLSX expands beyond the 300 MB safety limit")
                for entry in entries:
                    if entry.file_size > 0 and entry.file_size / max(entry.compress_size, 1) > 200:
                        raise ValueError("XLSX contains a suspiciously highly compressed entry")
        except zipfile.BadZipFile as exc:
            raise ValueError("XLSX archive is corrupted") from exc
    if extension == ".xls" and not content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise ValueError("XLS signature is invalid")
    if extension == ".csv":
        if b"\x00" in content[:8192]:
            raise ValueError("CSV contains binary data")
        try:
            content[:8192].decode("utf-8-sig")
        except UnicodeDecodeError:
            # Legacy CSV encodings are common; parser reads with replacement.
            pass


def _response(document: Document) -> DocumentResponse:
    return DocumentResponse.model_validate(document)


_DOCUMENT_LIST_COLUMNS = load_only(
    Document.id, Document.original_filename, Document.file_type, Document.file_size,
    Document.status, Document.page_count, Document.extraction_method,
    Document.processing_error, Document.created_at, Document.updated_at, Document.version,
)


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _apply_filters(
    stmt,
    *,
    state: str | None = None,
    file_type: str | None = None,
    supplier: str | None = None,
    invoice_number: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    if state:
        stmt = stmt.where(Document.status == state)
    if file_type:
        stmt = stmt.where(Document.file_type == file_type.lower().lstrip("."))
    if supplier:
        stmt = stmt.where(Document.extracted_data["supplier_name"].as_string().ilike(_like(supplier), escape="\\"))
    if invoice_number:
        stmt = stmt.where(Document.extracted_data["invoice_number"].as_string().ilike(_like(invoice_number), escape="\\"))
    # Only canonical ISO dates participate in precise date ranges. Ambiguous source
    # dates remain visible through the date-review warning and can be searched by text.
    if date_from:
        stmt = stmt.where(Document.invoice_date_iso >= date_from)
    if date_to:
        stmt = stmt.where(Document.invoice_date_iso <= date_to)
    return stmt


def _keyword_condition(query: str):
    term = _like(query)
    return or_(
        Document.original_filename.ilike(term, escape="\\"),
        Document.extracted_text.ilike(term, escape="\\"),
        Document.extracted_data["invoice_number"].as_string().ilike(term, escape="\\"),
        Document.extracted_data["supplier_name"].as_string().ilike(term, escape="\\"),
        Document.extracted_data["customer_name"].as_string().ilike(term, escape="\\"),
        Document.extracted_data["invoice_date"].as_string().ilike(term, escape="\\"),
        Document.extracted_data["currency"].as_string().ilike(term, escape="\\"),
        cast(Document.extracted_data["line_items"], Text).ilike(term, escape="\\"),
    )


@router.post("/documents/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_documents(
    files: list[UploadFile] = File(...),
    allow_duplicate: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bounded synchronous upload endpoint; blocking DB and filesystem work stays off the event loop."""
    if not _UPLOAD_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="Upload capacity is busy; retry shortly.", headers={"Retry-After": "5"})
    try:
        accepted: list[DocumentResponse] = []
        rejected: list[dict[str, str]] = []
        if not files:
            raise HTTPException(status_code=422, detail="At least one file is required")
        if len(files) > 10:
            raise HTTPException(status_code=413, detail="At most 10 files may be uploaded in one request")
        settings.storage_path.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        scope = document_scope(user)
        for upload in files:
            original_name = _safe_original_name(upload.filename)
            ext = Path(original_name).suffix.lower()
            stored_path: Path | None = None
            temp_path: Path | None = None
            try:
                if ext not in SUPPORTED_EXTENSIONS:
                    raise ValueError(f"Unsupported file extension: {ext or '(none)'}")
                # UploadFile is already spooled by Starlette; the sync route reads it
                # in a worker thread. Enforce both per-file and aggregate request caps.
                content = upload.file.read(MAX_UPLOAD_BYTES + 1)
                if len(content) > MAX_UPLOAD_BYTES:
                    raise ValueError(f"File exceeds the {settings.max_upload_mb} MB limit")
                total_bytes += len(content)
                if total_bytes > MAX_UPLOAD_REQUEST_BYTES:
                    raise ValueError(f"Upload request exceeds the {settings.upload_request_mb} MB total limit")
                _check_signature(ext, content)
                sha256 = hashlib.sha256(content).hexdigest()
                if not allow_duplicate:
                    # Deduplicate within the workspace, not merely for the uploader.
                    # Do not disclose the existing document ID across owner boundaries.
                    duplicate = db.scalar(
                        select(Document.id).where(
                            Document.tenant_id == user.tenant_id, Document.sha256 == sha256
                        ).order_by(Document.created_at.desc()).limit(1)
                    )
                    if duplicate:
                        rejected.append({"filename": original_name, "reason": "Duplicate content already exists in this workspace"})
                        continue
                stored_name = f"{uuid.uuid4().hex}{ext}"
                stored_path = settings.storage_path / stored_name
                temp_path = settings.storage_path / f".{stored_name}.uploading"
                temp_path.write_bytes(content)
                temp_path.replace(stored_path)
                temp_path = None
                document = Document(
                    id=str(uuid.uuid4()),
                    original_filename=original_name,
                    stored_filename=stored_name,
                    file_type=ext[1:],
                    mime_type=upload.content_type,
                    file_size=len(content),
                    sha256=sha256,
                    tenant_id=user.tenant_id,
                    owner_id=user.id,
                    status="pending",
                )
                db.add(document)
                db.flush()
                # The composite primary key closes the race where two default
                # uploads pass the friendly pre-check simultaneously. The legacy
                # allow_duplicate option remains explicit: duplicate documents may
                # be stored, while the first content reservation remains canonical.
                reservation_values = {
                    "tenant_id": user.tenant_id,
                    "sha256": sha256,
                    "document_id": document.id,
                }
                if allow_duplicate:
                    dialect = db.bind.dialect.name if db.bind is not None else ""
                    if dialect == "sqlite":
                        db.execute(sqlite_insert(DocumentHash).values(**reservation_values).on_conflict_do_nothing(
                            index_elements=["tenant_id", "sha256"]
                        ))
                    elif dialect == "postgresql":
                        db.execute(postgresql_insert(DocumentHash).values(**reservation_values).on_conflict_do_nothing(
                            index_elements=["tenant_id", "sha256"]
                        ))
                    elif db.get(DocumentHash, (user.tenant_id, sha256)) is None:
                        db.add(DocumentHash(**reservation_values))
                else:
                    db.add(DocumentHash(**reservation_values))
                    db.flush()
                add_event(db, document.id, "upload_accepted", "File passed initial upload checks")
                enqueue_document_job(db, document.id)
                db.commit()
                db.refresh(document)
                accepted.append(_response(document))
            except ValueError as exc:
                db.rollback()
                if stored_path and stored_path.exists():
                    stored_path.unlink(missing_ok=True)
                if temp_path and temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                rejected.append({"filename": original_name, "reason": str(exc)})
            except IntegrityError as exc:
                db.rollback()
                if stored_path and stored_path.exists():
                    stored_path.unlink(missing_ok=True)
                if temp_path and temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                existing = db.scalar(select(Document.id).where(Document.tenant_id == user.tenant_id, Document.sha256 == sha256).limit(1))
                if existing:
                    rejected.append({"filename": original_name, "reason": "Duplicate content already exists in this workspace"})
                else:
                    rejected.append({"filename": original_name, "reason": "Upload failed (database integrity constraint)"})
            except Exception as exc:
                db.rollback()
                if stored_path and stored_path.exists():
                    stored_path.unlink(missing_ok=True)
                if temp_path and temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                rejected.append({"filename": original_name, "reason": f"Upload failed ({type(exc).__name__})"})
            finally:
                upload.file.close()
        return UploadResponse(accepted=accepted, rejected=rejected)
    finally:
        _UPLOAD_SLOTS.release()


@router.get("/documents/stats")
def document_stats(
    state: str | None = Query(default=None, pattern="^(pending|processing|completed|failed)$"),
    file_type: str | None = Query(default=None, pattern="^(pdf|jpg|jpeg|png|tif|tiff|xlsx|xls|csv)$"),
    supplier: str | None = Query(default=None, max_length=200),
    invoice_number: str | None = Query(default=None, max_length=100),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return inexpensive, tenant-scoped counts without loading document payloads."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    stmt = _apply_filters(
        select(Document.status, func.count(Document.id)).where(document_scope(user)),
        state=state, file_type=file_type, supplier=supplier, invoice_number=invoice_number,
        date_from=date_from, date_to=date_to,
    ).group_by(Document.status)
    counts = {str(row[0]): int(row[1]) for row in db.execute(stmt).all()}
    total = sum(counts.values())
    return {
        "total": total,
        "completed": counts.get("completed", 0),
        "queued": counts.get("pending", 0) + counts.get("processing", 0),
        "failed": counts.get("failed", 0),
    }


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    q: str | None = Query(default=None, max_length=200),
    state: str | None = Query(default=None, pattern="^(pending|processing|completed|failed)$"),
    file_type: str | None = Query(default=None, pattern="^(pdf|jpg|jpeg|png|tif|tiff|xlsx|xls|csv)$"),
    supplier: str | None = Query(default=None, max_length=200),
    invoice_number: str | None = Query(default=None, max_length=100),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    stmt = _apply_filters(
        select(Document).options(_DOCUMENT_LIST_COLUMNS).where(document_scope(user)), state=state, file_type=file_type, supplier=supplier,
        invoice_number=invoice_number, date_from=date_from, date_to=date_to,
    )
    if q:
        stmt = stmt.where(_keyword_condition(q))
    stmt = stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)
    return [_response(document) for document in db.scalars(stmt).all()]


@router.get("/search")
def search_documents(
    q: str = Query(default="", max_length=200),
    mode: str = Query(default="hybrid", pattern="^(keyword|semantic|hybrid)$"),
    state: str | None = Query(default=None, pattern="^(pending|processing|completed|failed)$"),
    file_type: str | None = Query(default=None, pattern="^(pdf|jpg|jpeg|png|tif|tiff|xlsx|xls|csv)$"),
    supplier: str | None = Query(default=None, max_length=200),
    invoice_number: str | None = Query(default=None, max_length=100),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Tenant-scoped keyword/semantic/hybrid search with bounded vector projections."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    filters = dict(state=state, file_type=file_type, supplier=supplier, invoice_number=invoice_number, date_from=date_from, date_to=date_to)
    base = _apply_filters(select(Document).where(document_scope(user)), **filters)
    if not q.strip():
        rows = db.scalars(base.options(_DOCUMENT_LIST_COLUMNS).order_by(Document.created_at.desc()).offset(offset).limit(limit)).all()
        return {"query": q, "mode_requested": mode, "mode_used": "keyword", "filters_applied": {k:v for k,v in filters.items() if v is not None}, "results": [_response(row).model_dump(mode="json") for row in rows]}

    if mode == "keyword":
        keyword_rows = db.scalars(base.options(_DOCUMENT_LIST_COLUMNS).where(_keyword_condition(q)).order_by(Document.created_at.desc()).offset(offset).limit(limit)).all()
        return {"query": q, "mode_requested": mode, "mode_used": "keyword", "filters_applied": {k:v for k,v in filters.items() if v is not None}, "results": [_response(row).model_dump(mode="json") for row in keyword_rows]}

    # Make the outbound embedding request before acquiring a DB connection. The
    # session object is not queried until after Ollama returns.
    query_vector = create_embedding("search_query: " + q)
    if not query_vector:
        keyword_rows = db.scalars(base.options(_DOCUMENT_LIST_COLUMNS).where(_keyword_condition(q)).order_by(Document.created_at.desc()).offset(offset).limit(limit)).all()
        return {"query": q, "mode_requested": mode, "mode_used": "keyword_fallback", "filters_applied": {k:v for k,v in filters.items() if v is not None}, "results": [_response(row).model_dump(mode="json") for row in keyword_rows]}

    keyword_ids: list[str] = []
    if mode == "hybrid":
        keyword_stmt = (
            base.with_only_columns(Document.id)
            .where(_keyword_condition(q))
            .order_by(Document.created_at.desc())
            .limit(min(max(limit * 5 + offset, 200), 500))
        )
        keyword_ids = list(db.scalars(keyword_stmt).all())

    semantic_filters = {k:v for k,v in filters.items() if k != "state"}
    candidates_stmt = _apply_filters(
        select(Document.id, Document.embedding).where(document_scope(user), Document.status == "completed"),
        **semantic_filters,
    )
    if state:
        candidates_stmt = candidates_stmt.where(Document.status == state)
    candidates = db.execute(candidates_stmt.order_by(Document.created_at.desc()).limit(10_000)).all()
    # Release the SQL connection before Python-side vector scoring. Only scalar
    # IDs/embeddings are retained in memory during ranking.
    db.close()

    import math
    def cosine(left: list[float], right: list[float]) -> float:
        if not isinstance(right, list) or len(left) != len(right):
            return -1.0
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(a) ** 2 for a in left))
        right_norm = math.sqrt(sum(float(b) ** 2 for b in right))
        return dot / (left_norm * right_norm) if left_norm and right_norm else -1.0

    scores: dict[str, float] = {}
    threshold = settings.min_semantic_similarity
    for document_id, embedding in candidates:
        if isinstance(embedding, list) and embedding:
            similarity = cosine(query_vector, embedding)
            if similarity >= threshold:
                scores[document_id] = similarity

    if mode == "hybrid":
        for document_id in keyword_ids:
            # Preserve exact/keyword hits even when no embedding was generated.
            scores[document_id] = max(scores.get(document_id, -1.0), 0.35)

    ranked_ids = [doc_id for doc_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[offset:offset + limit]]
    if not ranked_ids:
        rows = []
    else:
        loaded = db.scalars(select(Document).options(_DOCUMENT_LIST_COLUMNS).where(document_scope(user), Document.id.in_(ranked_ids))).all()
        by_id = {row.id: row for row in loaded}
        rows = [by_id[doc_id] for doc_id in ranked_ids if doc_id in by_id]
    return {
        "query": q,
        "mode_requested": mode,
        "mode_used": mode,
        "filters_applied": {k:v for k,v in filters.items() if v is not None},
        "results": [{**_response(row).model_dump(mode="json"), "search_score": round(scores[row.id], 5)} for row in rows],
    }


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Permanently remove a document and its related data from the caller's workspace.

    Active jobs cannot be deleted, preventing a worker from racing file removal.
    The original file is first moved to a same-filesystem quarantine name. If the
    database transaction fails, it is restored; after commit it is unlinked.
    """
    document = db.scalar(
        select(Document)
        .where(Document.id == document_id, document_scope(user))
        .with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    active_job = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.status.in_(["queued", "running"]),
        ).limit(1)
    )
    if document.status in {"pending", "processing"} or active_job:
        raise HTTPException(
            status_code=409,
            detail="This document is queued or processing. Wait until processing finishes before deleting it.",
        )

    storage_root = settings.storage_path.resolve()
    stored_path = (storage_root / document.stored_filename).resolve()
    if stored_path.parent != storage_root:
        raise HTTPException(status_code=500, detail="Stored document path is invalid; deletion was stopped")

    quarantine_path = storage_root / f".{uuid.uuid4().hex}.deleting"
    staged_file = False
    if stored_path.exists():
        try:
            stored_path.replace(quarantine_path)
            staged_file = True
        except OSError as exc:
            raise HTTPException(status_code=503, detail="The original file could not be staged for deletion. Please retry.") from exc

    try:
        # Explicit deletes keep this behavior consistent on SQLite and PostgreSQL,
        # even if a deployment has legacy rows created before FK enforcement.
        db.execute(delete(ProcessingJob).where(ProcessingJob.document_id == document_id))
        db.execute(delete(ProcessingEvent).where(ProcessingEvent.document_id == document_id))
        db.execute(delete(DocumentHash).where(DocumentHash.document_id == document_id))
        db.delete(document)
        db.commit()
    except Exception as exc:
        db.rollback()
        if staged_file and quarantine_path.exists() and not stored_path.exists():
            try:
                quarantine_path.replace(stored_path)
            except OSError:
                # Keep the quarantined file rather than risking permanent data loss.
                pass
        raise HTTPException(status_code=500, detail="Document deletion failed; the database transaction was rolled back") from exc

    file_deleted = True
    if staged_file and quarantine_path.exists():
        try:
            quarantine_path.unlink()
        except OSError:
            file_deleted = False

    return {
        "status": "deleted",
        "document_id": document_id,
        "file_deleted": file_deleted,
        "related_data_deleted": True,
        "cleanup_note": None if file_deleted else "The document record was deleted, but its quarantined file needs storage cleanup.",
    }


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document = db.scalar(select(Document).where(Document.id == document_id, document_scope(user)))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return _response(document)


@router.get("/documents/{document_id}/status", response_model=ProcessingStatusResponse)
def get_processing_status(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document = db.scalar(select(Document).where(Document.id == document_id, document_scope(user)))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    job = db.scalar(
        select(ProcessingJob).where(ProcessingJob.document_id == document_id)
        .order_by(ProcessingJob.created_at.desc()).limit(1)
    )
    return ProcessingStatusResponse(
        document_id=document.id,
        document_status=document.status,
        queue_status=job.status if job else None,
        job_id=job.id if job else None,
        attempt_count=job.attempt_count if job else 0,
        max_attempts=job.max_attempts if job else 0,
        queue_created_at=job.created_at if job else None,
        started_at=job.started_at if job else None,
        finished_at=job.updated_at if job and job.status in {"completed", "failed"} else None,
        last_error=job.last_error if job else document.processing_error,
    )


@router.get("/documents/{document_id}/result", response_model=DocumentResultResponse)
def get_document_result(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document = db.scalar(select(Document).where(Document.id == document_id, document_scope(user)))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResultResponse.model_validate(document, from_attributes=True)


@router.patch("/documents/{document_id}/corrections", response_model=DocumentResultResponse)
def correct_document(document_id: str, request: CorrectionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document = db.scalar(select(Document).where(Document.id == document_id, document_scope(user)))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status != "completed" or not document.extracted_data:
        raise HTTPException(status_code=409, detail="Document must be completed before correction")
    allowed = set(InvoiceData.model_fields.keys())
    invalid = set(request.fields) - allowed
    if invalid:
        raise HTTPException(status_code=422, detail={"message": "Unknown correction field", "fields": sorted(invalid)})
    if request.expected_version != document.version:
        raise HTTPException(status_code=409, detail="Document was changed by another reviewer; reload before saving.")
    merged = dict(document.extracted_data)
    merged.update(request.fields)
    try:
        corrected = InvoiceData.model_validate(merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Correction values do not match the expected schema") from exc

    existing: list[dict[str, Any]] = []
    if corrected.invoice_number and corrected.supplier_name:
        candidates = db.execute(
            select(Document.id, Document.invoice_number_norm, Document.supplier_name_norm)
            .where(Document.tenant_id == user.tenant_id, Document.id != document_id, Document.status == "completed",
                   Document.invoice_number_norm == corrected.invoice_number.strip().casefold(),
                   Document.supplier_name_norm == corrected.supplier_name.strip().casefold())
            .limit(1)
        ).all()
        for candidate_id, candidate_number, candidate_supplier in candidates:
            existing.append({"invoice_number": candidate_number, "supplier_name": candidate_supplier})
    field_evidence = collect_field_evidence(document.extracted_text or "", corrected)
    errors, warnings = validate_invoice(corrected, existing, field_evidence)
    before = dict(document.extracted_data or {})
    overrides = dict(document.manual_overrides or {})
    overrides.update(request.fields)
    document.manual_overrides = overrides
    document.extracted_data = corrected.model_dump(mode="json")
    document.invoice_number_norm = corrected.invoice_number.strip().casefold() if corrected.invoice_number else None
    document.supplier_name_norm = corrected.supplier_name.strip().casefold() if corrected.supplier_name else None
    document.invoice_date_iso = corrected.invoice_date if corrected.invoice_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", corrected.invoice_date) else None
    document.extraction_method = "manual_override"
    # A correction is persisted even when Ollama is unavailable. Clear the old
    # vector first, commit the correction, release the DB connection for the
    # network call, then attach the new vector only if the row version is unchanged.
    document.embedding = None
    document.field_evidence = field_evidence
    document.validation_errors = errors
    document.validation_warnings = warnings
    snapshot = {
        "before": before,
        "after": corrected.model_dump(mode="json"),
        "corrected_by": user.email,
        "expected_version": request.expected_version,
    }
    db.add(ProcessingEvent(
        document_id=document_id,
        event_type="manual_correction",
        message=f"Manual correction by {user.email}; fields changed: {', '.join(sorted(request.fields))}"[:500],
        details=snapshot,
    ))
    try:
        db.commit()
    except StaleDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Document changed while this correction was being saved; reload and try again.") from exc
    db.refresh(document)
    saved_version = document.version
    correction_summary = "search_document: " + str(
    corrected.model_dump(mode="json")
)
    correction_summary = "search_document: " + str(
        corrected.model_dump(mode="json")
    )
    source_text = document.extracted_text or ""

    # Prioritize corrected invoice data within the embedding model's input limit.
    remaining_chars = max(0, 8_000 - len(correction_summary) - 1)

    embedding_text = (
        correction_summary
        + "\n"
        + source_text[:remaining_chars]
    )

    db.close()
    vector = create_embedding(embedding_text)

    if vector:
        db.execute(update(Document).where(
            Document.id == document_id, Document.version == saved_version
        ).values(embedding=vector))
        db.commit()

    refreshed = db.scalar(
        select(Document).where(Document.id == document_id, document_scope(user))
    )
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResultResponse.model_validate(
        refreshed, from_attributes=True
    )

@router.post("/documents/{document_id}/reprocess", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentResponse)
def reprocess_document(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document = db.scalar(select(Document).where(Document.id == document_id, document_scope(user)))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    path = settings.storage_path / document.stored_filename
    if not path.exists():
        raise HTTPException(status_code=410, detail="Original file is no longer available")
    active_job = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.status.in_(["queued", "running"]),
        ).limit(1)
    )
    if active_job or document.status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail="Document is already queued or processing")
    previous_extraction = dict(document.extracted_data or {})
    add_event(
        db, document_id, "reprocess_snapshot",
        "Previous extraction snapshot captured before reprocessing",
        details={"before": previous_extraction, "manual_overrides": dict(document.manual_overrides or {}),
                 "version": document.version},
    )
    document.status = "pending"
    document.processing_error = None
    latest_job = db.scalar(select(ProcessingJob).where(ProcessingJob.document_id == document_id).order_by(ProcessingJob.created_at.desc()).limit(1))
    if latest_job and latest_job.status in {"completed", "failed"}:
        latest_job.status = "queued"
        latest_job.attempt_count = 0
        latest_job.max_attempts = max(1, latest_job.max_attempts or 3)
        latest_job.available_at = datetime.now(timezone.utc)
        latest_job.locked_at = None
        latest_job.started_at = None
        latest_job.worker_id = None
        latest_job.last_error = None
        latest_job.updated_at = datetime.now(timezone.utc)
        add_event(db, document_id, "job_queued", "Existing processing job reused for reprocessing")
    else:
        enqueue_document_job(db, document.id)
    add_event(db, document_id, "reprocess_requested", "Document reprocessing requested; manual corrections are retained")
    db.commit()
    db.refresh(document)
    return _response(document)


@router.post("/documents/compare", response_model=CompareResult)
def compare_documents(request: CompareRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if len(set(request.document_ids)) != len(request.document_ids):
        raise HTTPException(status_code=422, detail="Document IDs must be unique")
    docs: list[tuple[str, InvoiceData]] = []
    for document_id in request.document_ids:
        document = db.scalar(select(Document).where(Document.id == document_id, document_scope(user)))
        if not document:
            raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")
        if document.status != "completed" or not document.extracted_data:
            raise HTTPException(status_code=409, detail=f"Document is not completed: {document_id}")
        docs.append((document.id, InvoiceData.model_validate(document.extracted_data)))
    result = compare_invoice_data(docs, request.fields)
    return CompareResult.model_validate(result)


@router.get("/documents/{document_id}/history")
def document_history(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.scalar(select(Document.id).where(Document.id == document_id, document_scope(user))):
        raise HTTPException(status_code=404, detail="Document not found")
    events = db.scalars(
        select(ProcessingEvent).where(ProcessingEvent.document_id == document_id)
        .order_by(ProcessingEvent.created_at.asc())
    ).all()
    return [{"event_type": event.event_type, "message": event.message, "details": event.details, "created_at": event.created_at} for event in events]
