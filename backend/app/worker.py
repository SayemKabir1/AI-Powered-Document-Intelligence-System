"""Durable document worker with atomic state transitions and graceful shutdown."""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
import threading
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app import models  # noqa: F401
from app.models import Document, ProcessingJob, utcnow
from app.services.jobs import add_event, process_document_job
from app.services.document_processor import DocumentProcessingError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("document_worker")
STOP_REQUESTED = threading.Event()


def recover_expired_jobs(db, lease_timeout_seconds: int | None = None) -> int:
    timeout = lease_timeout_seconds if lease_timeout_seconds is not None else settings.worker_lease_timeout_seconds
    cutoff = utcnow() - timedelta(seconds=timeout)
    expired = db.scalars(select(ProcessingJob).where(
        ProcessingJob.status == "running",
        ProcessingJob.locked_at.is_not(None),
        ProcessingJob.locked_at < cutoff,
    )).all()
    recovered = 0
    for job in expired:
        document = db.get(Document, job.document_id)
        # A completed document must never be extracted again merely because the
        # worker died between old/non-atomic finalization steps.
        if document and document.status == "completed":
            job.status = "completed"
            job.locked_at = None
            job.worker_id = None
            job.finished_at = utcnow()
            job.last_error = None
            add_event(db, job.document_id, "job_reconciled", "Completed document reconciled with its expired job lease")
        elif job.attempt_count < job.max_attempts:
            job.status = "queued"
            job.available_at = utcnow()
            job.locked_at = None
            job.worker_id = None
            job.last_error = "Worker lease expired; job returned to queue"
            if document:
                document.status = "pending"
            add_event(db, job.document_id, "job_recovered", "An abandoned processing job was returned to the queue")
        else:
            job.status = "failed"
            job.locked_at = None
            job.worker_id = None
            job.finished_at = utcnow()
            job.last_error = "Worker lease expired after the maximum number of attempts"
            if document:
                document.status = "failed"
                document.processing_error = "Processing worker stopped unexpectedly; retry limit reached"
            add_event(db, job.document_id, "job_failed", job.last_error)
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def claim_next_job(db, worker_id: str) -> str | None:
    """Claim the job and mark its document processing within one transaction."""
    now = utcnow()
    candidate_ids = db.scalars(select(ProcessingJob.id).where(
        ProcessingJob.status == "queued", ProcessingJob.available_at <= now
    ).order_by(ProcessingJob.created_at.asc()).limit(20)).all()
    for job_id in candidate_ids:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id))
        if not job:
            continue
        document = db.get(Document, job.document_id)
        if document is None:
            job.status = "failed"
            job.last_error = "Associated document no longer exists"
            job.finished_at = now
            db.commit()
            continue
        result = db.execute(update(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.status == "queued",
            ProcessingJob.available_at <= now,
        ).values(
            status="running", attempt_count=ProcessingJob.attempt_count + 1,
            locked_at=now, started_at=now, finished_at=None,
            worker_id=worker_id, updated_at=now,
        ).execution_options(synchronize_session=False))
        if result.rowcount == 1:
            document.status = "processing"
            document.processing_error = None
            add_event(db, document.id, "job_started", f"Worker started attempt {job.attempt_count + 1} of {job.max_attempts}")
            db.commit()
            return job_id
    db.rollback()
    return None


def _heartbeat_while_processing(stop_event: threading.Event, job_id: str, worker_id: str, factory: sessionmaker) -> None:
    interval = max(0.2, settings.worker_heartbeat_seconds)
    while not stop_event.wait(interval):
        heartbeat_db = factory()
        try:
            heartbeat_db.execute(update(ProcessingJob).where(
                ProcessingJob.id == job_id,
                ProcessingJob.status == "running",
                ProcessingJob.worker_id == worker_id,
            ).values(locked_at=utcnow(), updated_at=utcnow()))
            heartbeat_db.commit()
        except Exception:
            heartbeat_db.rollback()
            logger.exception("Unable to refresh worker lease for job %s", job_id)
        finally:
            heartbeat_db.close()


def process_next_job(session_factory: sessionmaker | None = None, worker_id: str | None = None) -> bool:
    factory = session_factory or SessionLocal
    who = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
    db = factory()
    job_id = None
    document_id = None
    try:
        recover_expired_jobs(db)
        job_id = claim_next_job(db, who)
        if not job_id:
            return False
        job = db.get(ProcessingJob, job_id)
        if not job:
            return True
        document_id = job.document_id
        attempt_count = job.attempt_count
        max_attempts = job.max_attempts
        path = settings.storage_path / (db.get(Document, document_id).stored_filename if db.get(Document, document_id) else "")
        db.close()
        db = None

        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(target=_heartbeat_while_processing,
            args=(heartbeat_stop, job_id, who, factory), name=f"job-heartbeat-{job_id[:8]}", daemon=True)
        heartbeat.start()
        processing_error = None
        try:
            if not path.exists():
                raise DocumentProcessingError("Original file was not found")
            succeeded = process_document_job(document_id, str(path), session_factory=factory, job_id=job_id, worker_id=who)
            return succeeded
        except Exception as exc:
            processing_error = exc
            logger.exception("Processing failed for document %s", document_id)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=max(1.0, settings.worker_heartbeat_seconds + 0.5))

        # Failure handling is one conditional transaction. Deterministic parser
        # errors do not waste retries; transient errors retain bounded backoff.
        db = factory()
        job = db.scalar(select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.status == "running",
            ProcessingJob.worker_id == who,
        ))
        document = db.get(Document, document_id)
        if not job:
            db.rollback()
            return True  # lease was recovered/reassigned; stale worker must not overwrite it
        deterministic = isinstance(processing_error, DocumentProcessingError)
        retryable = not deterministic and job.attempt_count < job.max_attempts
        message = str(processing_error)[:300] if deterministic else f"Processing failed ({type(processing_error).__name__})"
        job.last_error = message[:500]
        job.locked_at = None
        job.worker_id = None
        job.updated_at = utcnow()
        if retryable:
            job.status = "queued"
            job.available_at = utcnow() + timedelta(seconds=settings.worker_retry_delay_seconds * max(1, attempt_count))
            if document:
                document.status = "pending"
                document.processing_error = message
            add_event(db, document_id, "job_retry_scheduled", f"Transient processing failure on attempt {attempt_count}; retry scheduled")
        else:
            job.status = "failed"
            job.finished_at = utcnow()
            if document:
                document.status = "failed"
                document.processing_error = message
            add_event(db, document_id, "job_failed", f"Processing failed after {attempt_count} attempt(s)")
        db.commit()
        return True
    except Exception:
        if db is not None:
            db.rollback()
        logger.exception("Unexpected error while handling a processing job")
        return False
    finally:
        if db is not None:
            db.close()


def run_forever(poll_seconds: float | None = None) -> None:
    Base.metadata.create_all(bind=engine)
    from app.db import run_compatibility_migrations
    run_compatibility_migrations(engine)
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    STOP_REQUESTED.clear()
    def _request_stop(signum, _frame):
        logger.info("Shutdown signal %s received; stop claiming new jobs", signum)
        STOP_REQUESTED.set()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    delay = poll_seconds if poll_seconds is not None else settings.worker_poll_seconds
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("Document worker started (%s); polling every %.2fs", worker_id, delay)
    while not STOP_REQUESTED.is_set():
        try:
            worked = process_next_job(worker_id=worker_id)
            if not worked:
                STOP_REQUESTED.wait(delay)
        except Exception:
            logger.exception("Worker loop failed")
            STOP_REQUESTED.wait(max(delay, 1.0))
    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    run_forever()
