from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db import SessionLocal
from app.models import Document, ProcessingEvent, ProcessingJob, utcnow
from app.schemas import InvoiceData
from app.services.document_processor import process_document, DocumentProcessingError
from app.services.extractor import extract_invoice, create_embedding
from app.services.validation import validate_invoice
from app.services.evidence import collect_field_evidence

logger = logging.getLogger(__name__)


def add_event(db: Session, document_id: str, event_type: str, message: str, details: dict | None = None) -> None:
    db.add(ProcessingEvent(document_id=document_id, event_type=event_type, message=message[:500], details=details))


def enqueue_document_job(db: Session, document_id: str, max_attempts: int = 3) -> ProcessingJob:
    """Keep at most one active job and reuse a terminal row for reprocessing."""
    active = db.scalar(select(ProcessingJob).where(
        ProcessingJob.document_id == document_id,
        ProcessingJob.status.in_(["queued", "running"]),
    ).limit(1))
    if active:
        return active
    job = db.scalar(select(ProcessingJob).where(
        ProcessingJob.document_id == document_id
    ).order_by(ProcessingJob.created_at.desc()).limit(1))
    now = utcnow()
    if job:
        job.status = "queued"
        job.attempt_count = 0
        job.max_attempts = max_attempts
        job.available_at = now
        job.locked_at = None
        job.started_at = None
        job.finished_at = None
        job.worker_id = None
        job.last_error = None
        job.updated_at = now
    else:
        job = ProcessingJob(
            id=str(uuid4()), document_id=document_id, status="queued",
            attempt_count=0, max_attempts=max_attempts, available_at=now,
        )
        db.add(job)
    add_event(db, document_id, "job_queued", f"Document processing job queued (up to {max_attempts} attempts)")
    return job


def _invoice_date_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
        return parsed.date().isoformat()
    except ValueError:
        return None


def _embedding_summary(data: InvoiceData, extracted_text: str) -> str:
    if not extracted_text.strip() and not any(getattr(data, name) is not None for name in (
        "invoice_number", "supplier_name", "customer_name", "total"
    )):
        return ""
    line_summary = "; ".join(
        f"{item.description or 'item'} quantity {item.quantity} amount {item.amount}"
        for item in data.line_items[:50]
    )
    summary = " | ".join(part for part in (
        f"invoice {data.invoice_number}" if data.invoice_number else "",
        f"supplier {data.supplier_name}" if data.supplier_name else "",
        f"customer {data.customer_name}" if data.customer_name else "",
        f"total {data.total} {data.currency or ''}" if data.total is not None else "",
        line_summary,
        extracted_text[:5_000],
    ) if part)
    return "search_document: " + summary if summary else ""


def _duplicate_invoices(db: Session, document: Document, data: InvoiceData) -> list[dict]:
    if not data.invoice_number or not data.supplier_name:
        return []
    number = data.invoice_number.strip().casefold()
    supplier = data.supplier_name.strip().casefold()
    stmt = select(Document.id, Document.invoice_number_norm, Document.supplier_name_norm).where(
        Document.status == "completed",
        Document.id != document.id,
        Document.tenant_id == document.tenant_id,
        Document.invoice_number_norm == number,
        Document.supplier_name_norm == supplier,
    ).limit(1)
    return [
        {"invoice_number": row[1], "supplier_name": row[2]}
        for row in db.execute(stmt).all()
    ]


def process_document_job(
    document_id: str,
    stored_path: str,
    session_factory: sessionmaker | None = None,
    *,
    job_id: str | None = None,
    worker_id: str | None = None,
) -> bool:
    """Run CPU/OCR/LLM work without holding a DB connection, then persist atomically."""
    factory = session_factory or SessionLocal
    db = factory()
    try:
        document = db.get(Document, document_id)
        if document is None:
            raise DocumentProcessingError("Document record no longer exists")
        manual_overrides = dict(document.manual_overrides or {})
        tenant_id = document.tenant_id
        db.close()
        db = None

        text, page_count, metadata = process_document(Path(stored_path))
        data, method = extract_invoice(text)
        if manual_overrides:
            payload = data.model_dump(mode="python")
            payload.update(manual_overrides)
            data = InvoiceData.model_validate(payload)

        embedding_source = _embedding_summary(data, text)
        embedding = create_embedding(embedding_source) if embedding_source else None
        field_evidence = collect_field_evidence(text, data)

        db = factory()
        current = db.get(Document, document_id)
        if current is None:
            raise DocumentProcessingError("Document record disappeared during processing")
        duplicates = _duplicate_invoices(db, current, data)
        errors, warnings = validate_invoice(data, duplicates, field_evidence)
        if metadata.get("rows_truncated"):
            warnings.append({
                "code": "spreadsheet_row_limit_reached", "field": "document",
                "message": "Spreadsheet processing reached the configured row limit; some rows may not have been processed.",
            })
        if method == "ollama+rules":
            warnings.append({
                "code": "llm_rule_conflict_review_required", "field": "extraction",
                "message": "The language model disagreed with deterministic extraction. Rule-grounded values were preferred; review the original document.",
            })
        if method == "rules_prompt_review":
            warnings.append({
                "code": "untrusted_instruction_or_label_conflict", "field": "extraction",
                "message": "Instruction-like text or conflicting invoice labels were detected. The LLM was bypassed; verify all extracted values against the original document.",
            })
        if re.search(r"(?i)ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions|disregard\s+(?:all\s+)?(?:previous|prior|above)\s+instructions|reveal\s+(?:the\s+)?(?:system\s+prompt|credentials|secrets)|(?:fabricate|invent|make\s+up)\s+(?:the\s+)?(?:invoice|supplier|vendor|total|amount|customer)|override\s+(?:the\s+)?(?:extraction|invoice|supplier|total)|set\s+(?:the\s+)?(?:supplier|invoice\s+number|total)\s+to\s+", text):
            warnings.append({
                "code": "prompt_injection_detected", "field": "extracted_text",
                "message": "Instruction-like text was detected inside the document. Treat the document as untrusted and manually verify extracted values.",
            })
        if metadata.get("low_ocr_confidence"):
            warnings.append({
                "code": "low_ocr_confidence", "field": "document",
                "message": "OCR confidence is below the configured review threshold; verify extracted values against the original scan.",
            })

        current.status = "completed"
        current.processing_error = None
        current.page_count = page_count
        current.ocr_confidence = metadata.get("ocr_mean_confidence")
        current.extracted_text = text[:2_000_000]
        current.extracted_data = data.model_dump(mode="json")
        current.field_evidence = field_evidence
        current.embedding = embedding
        current.validation_errors = errors
        current.validation_warnings = warnings
        current.invoice_date_iso = _invoice_date_iso(data.invoice_date)
        current.invoice_number_norm = data.invoice_number.strip().casefold() if data.invoice_number else None
        current.supplier_name_norm = data.supplier_name.strip().casefold() if data.supplier_name else None
        current.extraction_method = "manual_override" if manual_overrides else method
        add_event(db, document_id, "processing_completed", f"Processed using {metadata.get('kind', 'document')} pipeline and {method} extraction")

        if job_id:
            job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id))
            if not job or job.status != "running" or (worker_id and job.worker_id != worker_id):
                db.rollback()
                logger.warning("Ignoring stale worker result for job %s", job_id)
                return False
            job.status = "completed"
            job.locked_at = None
            job.worker_id = None
            job.finished_at = utcnow()
            job.last_error = None
            job.updated_at = utcnow()
            add_event(db, document_id, "job_completed", f"Document job completed on attempt {job.attempt_count}")
        db.commit()
        return True
    except Exception:
        if db is not None:
            db.rollback()
        raise
    finally:
        if db is not None:
            db.close()
