from io import BytesIO
import pytest
import fitz

def test_health_route(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_upload_rejects_unsupported_extension(client):
    response = client.post("/api/documents/upload", files=[("files", ("payload.exe", b"hello", "application/octet-stream"))])
    assert response.status_code == 202
    assert response.json()["accepted"] == []
    assert "Unsupported file extension" in response.json()["rejected"][0]["reason"]

def test_upload_queues_durable_job_and_worker_processes_pdf(client, run_queued_jobs):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox((50, 50, 550, 350), "Invoice No: TEST-1\nInvoice Date: 2026-05-01\nSupplier: Example LLC\nCustomer: Example Customer\nSubtotal: 10.00\nTax: 1.00\nTotal: 11.00\nCurrency: USD")
    content = pdf.tobytes()
    pdf.close()
    response = client.post("/api/documents/upload", files=[("files", ("invoice.pdf", content, "application/pdf"))])
    assert response.status_code == 202
    payload = response.json()
    assert len(payload["accepted"]) == 1
    document_id = payload["accepted"][0]["id"]
    # Upload returns before processing; the database-backed worker completes the persisted job.
    queued = client.get(f"/api/documents/{document_id}/status").json()
    assert queued["document_status"] == "pending"
    assert queued["queue_status"] == "queued"
    assert queued["attempt_count"] == 0
    assert run_queued_jobs() >= 1
    detail = client.get(f"/api/documents/{document_id}/result")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    finished = client.get(f"/api/documents/{document_id}/status").json()
    assert finished["queue_status"] == "completed"
    assert finished["attempt_count"] == 1
    assert detail.json()["extracted_data"]["invoice_number"] == "TEST-1"
    assert detail.json()["extracted_data"]["total"] == 11.0
    assert detail.json()["field_evidence"]["invoice_number"] is not None


def test_semantic_search_falls_back_to_keyword_when_ollama_is_disabled(client, run_queued_jobs):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox((50, 50, 550, 350), "Invoice No: SEARCH-99\nInvoice Date: 2026-05-01\nSupplier: Searchable Example\nSubtotal: 10.00\nTax: 1.00\nTotal: 11.00")
    content = pdf.tobytes()
    pdf.close()
    response = client.post("/api/documents/upload", files=[("files", ("search-invoice.pdf", content, "application/pdf"))])
    assert response.status_code == 202
    run_queued_jobs()
    result = client.get("/api/search", params={"q": "SEARCH-99", "mode": "semantic"})
    assert result.status_code == 200
    payload = result.json()
    assert payload["mode_used"] == "keyword_fallback"
    assert len(payload["results"]) == 1
    assert payload["results"][0]["original_filename"] == "search-invoice.pdf"


def test_business_api_requires_authenticated_session(client):
    from app.core.auth import get_current_user
    from app.main import app
    override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = client.get("/api/documents")
        assert response.status_code == 401
    finally:
        if override is not None:
            app.dependency_overrides[get_current_user] = override


def test_demo_workspace_seeds_dedicated_demo_identity(client, monkeypatch):
    import app.main as main_module
    from app.core.config import settings
    from app.db import Base
    from app.models import User
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    # Exercise the clean-install path in an isolated in-memory database.
    isolated_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=isolated_engine)
    isolated_sessions = sessionmaker(
        bind=isolated_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    monkeypatch.setattr(main_module, "SessionLocal", isolated_sessions)
    monkeypatch.setattr(settings, "demo_user_email", "public-demo@local.invalid")
    main_module.ensure_demo_workspace()

    with isolated_sessions() as db:
        demo_user = db.scalar(select(User).where(User.email == "public-demo@local.invalid"))
        assert demo_user is not None
        assert demo_user.role == "admin"
        assert demo_user.is_active is True
    isolated_engine.dispose()


def test_public_demo_mode_allows_document_api_without_session(client, monkeypatch):
    from app.core.auth import get_current_user, hash_password
    from app.core.config import settings
    from app.main import app
    from app.models import User
    from conftest import TestingSessionLocal

    # Seed the same dedicated identity created by the demo startup routine.
    with TestingSessionLocal() as db:
        db.add(User(
            id="public-demo-test-user", tenant_id="test-tenant",
            email="public-demo@local.invalid",
            password_hash=hash_password("demo-password-for-tests-only"),
            role="admin", is_active=True,
        ))
        db.commit()

    monkeypatch.setattr(settings, "demo_mode", True)
    override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = client.get("/api/search", params={"q": "invoice", "mode": "keyword"})
        assert response.status_code == 200
        assert response.json()["results"] == []

        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_textbox((50, 50, 550, 200), "Invoice Number: DEMO-OPEN-1\nSupplier: Public Demo Sample Co\nTotal: 12.00")
        content = pdf.tobytes()
        pdf.close()
        uploaded = client.post(
            "/api/documents/upload",
            files=[("files", ("public-demo-sample.pdf", content, "application/pdf"))],
        )
        assert uploaded.status_code == 202
        assert len(uploaded.json()["accepted"]) == 1
    finally:
        if override is not None:
            app.dependency_overrides[get_current_user] = override


def test_upload_rejects_file_with_pdf_extension_but_wrong_signature(client):
    response = client.post("/api/documents/upload", files=[("files", ("fake.pdf", b"not a PDF", "application/pdf"))])
    assert response.status_code == 202
    assert response.json()["accepted"] == []
    assert "signature is invalid" in response.json()["rejected"][0]["reason"]


def test_path_traversal_filename_is_sanitized(client):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox((50, 50, 550, 200), "Invoice Number: SAFE-1\nSupplier: Safe Co\nTotal: 5.00")
    content = pdf.tobytes()
    pdf.close()
    response = client.post("/api/documents/upload", files=[("files", ("../../nested/evil.pdf", content, "application/pdf"))])
    assert response.status_code == 202
    assert len(response.json()["accepted"]) == 1
    accepted = response.json()["accepted"][0]
    assert accepted["original_filename"] == "evil.pdf"
    assert ".." not in accepted["original_filename"]


def test_xlsx_compression_bomb_is_rejected(client):
    import io
    import zipfile
    from app.api.routes import _check_signature
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("xl/workbook.xml", "workbook")
        archive.writestr("xl/worksheets/sheet1.xml", "A" * 500_000)
    with pytest.raises(ValueError, match="highly compressed"):
        _check_signature(".xlsx", payload.getvalue())


def test_compare_rejects_unknown_field_names(client):
    response = client.post("/api/documents/compare", json={"document_ids": ["a", "b"], "fields": ["invoice_number", "password"]})
    assert response.status_code == 422


def test_reprocess_rejects_document_already_pending(client):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox((50, 50, 550, 200), "Invoice Number: PENDING-1\nSupplier: Example Co\nTotal: 5.00")
    content = pdf.tobytes()
    pdf.close()
    response = client.post("/api/documents/upload", files=[("files", ("pending.pdf", content, "application/pdf"))])
    assert response.status_code == 202
    document_id = response.json()["accepted"][0]["id"]
    # The API must reject reprocessing while the durable job is still queued.
    from conftest import TestingSessionLocal
    from app.models import Document
    db = TestingSessionLocal()
    try:
        document = db.get(Document, document_id)
        document.status = "pending"
        db.commit()
    finally:
        db.close()
    retry = client.post(f"/api/documents/{document_id}/reprocess")
    assert retry.status_code == 409


def test_compare_two_completed_documents_reports_total_mismatch(client, run_queued_jobs):
    document_ids = []
    for invoice_number, total in (("CROSS-1", "11.00"), ("CROSS-1", "12.00")):
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_textbox((50, 50, 550, 250), f"Invoice Number: {invoice_number}\nInvoice Date: 2026-05-01\nSupplier: Example LLC\nSubtotal: 10.00\nTax: 1.00\nTotal: {total}")
        content = pdf.tobytes()
        pdf.close()
        response = client.post("/api/documents/upload", files=[("files", (f"{invoice_number}-{total}.pdf", content, "application/pdf"))])
        assert response.status_code == 202
        document_ids.append(response.json()["accepted"][0]["id"])
    run_queued_jobs()
    compared = client.post("/api/documents/compare", json={"document_ids": document_ids, "fields": ["total"]})
    assert compared.status_code == 200
    result = compared.json()
    assert result["matching"] is False
    assert result["differences"][0]["field"] == "total"


def _make_pdf_invoice(invoice_number: str, supplier: str, total: str = "11.00", line_items: str = "") -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    text = (
        f"Invoice Number: {invoice_number}\nInvoice Date: 2026-05-01\nSupplier: {supplier}\n"
        f"Customer: Example Customer\nSubtotal: 10.00\nTax: 1.00\nTotal: {total}\nCurrency: USD\n{line_items}"
    )
    page.insert_textbox((50, 50, 550, 450), text)
    data = pdf.tobytes()
    pdf.close()
    return data



def test_delete_document_removes_original_file_and_all_related_data(client, run_queued_jobs):
    from conftest import TestingSessionLocal
    from app.core.config import settings
    from app.models import Document, DocumentHash, ProcessingEvent, ProcessingJob
    from sqlalchemy import select, func

    content = _make_pdf_invoice("DELETE-101", "Delete Test Co")
    uploaded = client.post(
        "/api/documents/upload",
        files=[("files", ("delete-me.pdf", content, "application/pdf"))],
    )
    assert uploaded.status_code == 202
    document_id = uploaded.json()["accepted"][0]["id"]
    assert run_queued_jobs() >= 1

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        stored_path = settings.storage_path / document.stored_filename
        assert stored_path.is_file()
        assert db.scalar(select(func.count()).select_from(ProcessingEvent).where(ProcessingEvent.document_id == document_id)) >= 1
        assert db.scalar(select(func.count()).select_from(ProcessingJob).where(ProcessingJob.document_id == document_id)) == 1
        assert db.scalar(select(func.count()).select_from(DocumentHash).where(DocumentHash.document_id == document_id)) == 1

    deleted = client.delete(f"/api/documents/{document_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["file_deleted"] is True
    assert deleted.json()["related_data_deleted"] is True
    assert not stored_path.exists()

    with TestingSessionLocal() as db:
        assert db.get(Document, document_id) is None
        assert db.scalar(select(func.count()).select_from(ProcessingEvent).where(ProcessingEvent.document_id == document_id)) == 0
        assert db.scalar(select(func.count()).select_from(ProcessingJob).where(ProcessingJob.document_id == document_id)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentHash).where(DocumentHash.document_id == document_id)) == 0

    assert client.get(f"/api/documents/{document_id}").status_code == 404
    assert client.get("/api/search", params={"q": "DELETE-101", "mode": "keyword"}).json()["results"] == []
    # Deleting the original record also releases its content reservation.
    reuploaded = client.post(
        "/api/documents/upload",
        files=[("files", ("delete-me-again.pdf", content, "application/pdf"))],
    )
    assert len(reuploaded.json()["accepted"]) == 1


def test_delete_document_rejects_queued_or_processing_document(client):
    from conftest import TestingSessionLocal
    from app.core.config import settings
    from app.models import Document, ProcessingJob
    from sqlalchemy import select

    content = _make_pdf_invoice("DELETE-ACTIVE-1", "Active Delete Co")
    uploaded = client.post(
        "/api/documents/upload",
        files=[("files", ("active-delete.pdf", content, "application/pdf"))],
    )
    document_id = uploaded.json()["accepted"][0]["id"]
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        original_path = settings.storage_path / document.stored_filename
        assert original_path.is_file()
        assert db.scalar(select(ProcessingJob.id).where(ProcessingJob.document_id == document_id)) is not None

    response = client.delete(f"/api/documents/{document_id}")
    assert response.status_code == 409
    assert original_path.is_file()
    assert client.get(f"/api/documents/{document_id}").status_code == 200


def test_delete_document_respects_reviewer_ownership(client):
    from conftest import TestingSessionLocal
    from app.core.auth import get_current_user
    from app.main import app
    from app.core.config import settings
    from app.models import Document, Tenant, User
    from sqlalchemy import select

    content = _make_pdf_invoice("DELETE-SCOPE-1", "Scoped Delete Co")
    uploaded = client.post(
        "/api/documents/upload",
        files=[("files", ("owned-by-admin.pdf", content, "application/pdf"))],
    )
    document_id = uploaded.json()["accepted"][0]["id"]
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        original_path = settings.storage_path / document.stored_filename
        reviewer = User(
            id="delete-reviewer", tenant_id="test-tenant", email="reviewer-delete@example.invalid",
            password_hash="not-used-in-this-test", role="reviewer", is_active=True,
        )
        db.add(reviewer)
        db.commit()

    original_override = app.dependency_overrides[get_current_user]
    app.dependency_overrides[get_current_user] = lambda: reviewer
    try:
        response = client.delete(f"/api/documents/{document_id}")
        assert response.status_code == 404
        assert client.get(f"/api/documents/{document_id}").status_code == 404
        assert original_path.is_file()
        with TestingSessionLocal() as db:
            assert db.get(Document, document_id) is not None
    finally:
        app.dependency_overrides[get_current_user] = original_override

def test_search_filters_by_status_type_supplier_and_invoice(client, run_queued_jobs):
    for invoice_number, supplier in (("FILT-101", "Alpha Supplies"), ("FILT-202", "Beta Goods")):
        response = client.post(
            "/api/documents/upload",
            files=[("files", (f"{invoice_number}.pdf", _make_pdf_invoice(invoice_number, supplier), "application/pdf"))],
        )
        assert response.status_code == 202
    run_queued_jobs()
    result = client.get("/api/search", params={"supplier": "Alpha", "invoice_number": "FILT-101", "file_type": "pdf", "state": "completed"})
    assert result.status_code == 200
    records = result.json()["results"]
    assert len(records) == 1
    assert records[0]["original_filename"] == "FILT-101.pdf"


def test_manual_correction_updates_line_items_and_revalidates(client, run_queued_jobs):
    data = _make_pdf_invoice("LINE-101", "Line Item Co", line_items="Line Item: Widget | Quantity: 2 | Unit Price: 5.00 | Amount: 10.00")
    response = client.post("/api/documents/upload", files=[("files", ("line-item.pdf", data, "application/pdf"))])
    document_id = response.json()["accepted"][0]["id"]
    run_queued_jobs()
    current = client.get(f"/api/documents/{document_id}/result").json()
    updated = client.patch(
        f"/api/documents/{document_id}/corrections",
        json={"expected_version": current["version"], "fields": {"line_items": [{"description": "Corrected Widget", "quantity": 2, "unit_price": 5, "amount": 10}]}, "corrected_by": "pytest"},
    )
    assert updated.status_code == 200
    assert updated.json()["extracted_data"]["line_items"][0]["description"] == "Corrected Widget"
    history = client.get(f"/api/documents/{document_id}/history").json()
    assert any(event["event_type"] == "manual_correction" for event in history)


def test_semantic_mode_ranks_persisted_vectors_when_embedding_is_available(client, run_queued_jobs, monkeypatch):
    from conftest import TestingSessionLocal
    from app.models import Document
    import app.api.routes as routes_module

    ids = []
    for number, supplier in (("SEM-1", "North Star"), ("SEM-2", "South Wind")):
        response = client.post(
            "/api/documents/upload",
            files=[("files", (f"{number}.pdf", _make_pdf_invoice(number, supplier), "application/pdf"))],
        )
        ids.append(response.json()["accepted"][0]["id"])
    run_queued_jobs()
    db = TestingSessionLocal()
    try:
        db.get(Document, ids[0]).embedding = [1.0, 0.0]
        db.get(Document, ids[1]).embedding = [0.0, 1.0]
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(routes_module, "create_embedding", lambda _query: [1.0, 0.0])
    response = client.get("/api/search", params={"q": "meaning-based query", "mode": "semantic"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode_used"] == "semantic"
    assert payload["results"][0]["id"] == ids[0]


def test_invalid_iso_date_range_is_rejected(client):
    response = client.get("/api/search", params={"date_from": "2026-12-31", "date_to": "2026-01-01"})
    assert response.status_code == 422


def test_worker_retries_and_marks_permanently_corrupted_pdf_failed(client, run_queued_jobs, monkeypatch):
    from conftest import TestingSessionLocal
    from app.models import Document, ProcessingJob
    from sqlalchemy import select
    from app.core.config import settings

    monkeypatch.setattr(settings, "worker_retry_delay_seconds", 0)
    response = client.post("/api/documents/upload", files=[("files", ("corrupt.pdf", b"%PDF-this-is-not-a-valid-pdf", "application/pdf"))])
    document_id = response.json()["accepted"][0]["id"]
    run_queued_jobs()
    result = client.get(f"/api/documents/{document_id}/status").json()
    assert result["document_status"] == "failed"
    assert result["queue_status"] == "failed"
    assert result["attempt_count"] == 1
    db = TestingSessionLocal()
    try:
        jobs = db.scalars(select(ProcessingJob).where(ProcessingJob.document_id == document_id)).all()
        assert len(jobs) == 1
        assert jobs[0].attempt_count == 1
    finally:
        db.close()


def test_failed_job_can_be_requeued_for_manual_reprocessing(client, run_queued_jobs, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "worker_retry_delay_seconds", 0)
    uploaded = client.post(
        "/api/documents/upload",
        files=[("files", ("retry-corrupt.pdf", b"%PDF-still-not-valid", "application/pdf"))],
    )
    assert uploaded.status_code == 202
    document_id = uploaded.json()["accepted"][0]["id"]

    run_queued_jobs()
    failed = client.get(f"/api/documents/{document_id}/status").json()
    assert failed["document_status"] == "failed"
    assert failed["queue_status"] == "failed"
    assert failed["attempt_count"] == 1

    reprocess = client.post(f"/api/documents/{document_id}/reprocess")
    assert reprocess.status_code == 202
    assert reprocess.json()["status"] == "pending"
    queued = client.get(f"/api/documents/{document_id}/status").json()
    assert queued["document_status"] == "pending"
    assert queued["queue_status"] == "queued"
    assert queued["attempt_count"] == 0


def test_session_login_me_and_csrf_protection(client):
    from app.core.auth import get_current_user
    from app.main import app
    override = app.dependency_overrides.pop(get_current_user, None)
    try:
        login = client.post("/api/auth/login", json={
            "email": "admin@example.invalid",
            "password": "test-password-long-enough",
        })
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "admin"
        assert client.get("/api/auth/me").status_code == 200
        assert client.post("/api/auth/logout").status_code == 403
        csrf = client.cookies.get("docintel_csrf")
        assert csrf
        logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 200
        assert client.get("/api/auth/me").status_code == 401
    finally:
        if override is not None:
            app.dependency_overrides[get_current_user] = override


def test_reviewer_cannot_read_another_tenants_document(client, run_queued_jobs):
    from conftest import TestingSessionLocal
    from app.core.auth import get_current_user
    from app.main import app
    from app.models import Tenant, User
    from app.core.auth import hash_password
    import uuid

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox((50, 50, 550, 350), "Invoice No: TENANT-1\nInvoice Date: 2026-05-01\nSupplier: Tenant Supplier\nCustomer: Client\nSubtotal: 10\nTax: 1\nTotal: 11\nCurrency: USD")
    content = pdf.tobytes(); pdf.close()
    uploaded = client.post("/api/documents/upload", files=[("files", ("tenant-private.pdf", content, "application/pdf"))])
    document_id = uploaded.json()["accepted"][0]["id"]
    run_queued_jobs()

    other_tenant_id = str(uuid.uuid4())
    other_user = User(
        id=str(uuid.uuid4()), tenant_id=other_tenant_id,
        email="other-reviewer@example.invalid", password_hash=hash_password("another-password-long"),
        role="reviewer", is_active=True,
    )
    with TestingSessionLocal() as db:
        db.add(Tenant(id=other_tenant_id, name="Other workspace"))
        db.add(other_user)
        db.commit()

    override = app.dependency_overrides[get_current_user]
    app.dependency_overrides[get_current_user] = lambda: other_user
    try:
        assert client.get(f"/api/documents/{document_id}/result").status_code == 404
        assert client.get(f"/api/documents/{document_id}/history").status_code == 404
        assert client.patch(f"/api/documents/{document_id}/corrections", json={"expected_version": 1, "fields": {"supplier_name": "Stolen"}}).status_code == 404
    finally:
        app.dependency_overrides[get_current_user] = override


def test_correction_uses_optimistic_version_and_records_snapshot(client, run_queued_jobs):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox((50, 50, 550, 350), "Invoice No: VERSION-1\nInvoice Date: 2026-05-01\nSupplier: Version Co\nCustomer: Client\nSubtotal: 10\nTax: 1\nTotal: 11\nCurrency: USD")
    content = pdf.tobytes(); pdf.close()
    uploaded = client.post("/api/documents/upload", files=[("files", ("version.pdf", content, "application/pdf"))])
    document_id = uploaded.json()["accepted"][0]["id"]
    run_queued_jobs()
    original = client.get(f"/api/documents/{document_id}/result").json()
    saved = client.patch(f"/api/documents/{document_id}/corrections", json={
        "expected_version": original["version"], "fields": {"supplier_name": "Corrected Version Co"}
    })
    assert saved.status_code == 200
    stale = client.patch(f"/api/documents/{document_id}/corrections", json={
        "expected_version": original["version"], "fields": {"customer_name": "Stale edit"}
    })
    assert stale.status_code == 409
    history = client.get(f"/api/documents/{document_id}/history").json()
    event = next(item for item in history if item["event_type"] == "manual_correction")
    assert event["details"]["before"]["supplier_name"] == "Version Co"
    assert event["details"]["after"]["supplier_name"] == "Corrected Version Co"


def test_duplicate_upload_is_rejected_within_workspace(client):
    import hashlib
    from conftest import TestingSessionLocal
    from app.models import DocumentHash

    content = _make_pdf_invoice("DUP-001", "Duplicate Supplier")
    first = client.post("/api/documents/upload", files=[("files", ("duplicate.pdf", content, "application/pdf"))])
    second = client.post("/api/documents/upload", files=[("files", ("duplicate-copy.pdf", content, "application/pdf"))])
    assert first.status_code == 202
    assert len(first.json()["accepted"]) == 1
    assert second.status_code == 202
    assert second.json()["accepted"] == []
    assert "Duplicate content" in second.json()["rejected"][0]["reason"]

    # A database reservation backs the friendly pre-check and closes the race
    # where two independent upload requests pass the pre-check simultaneously.
    db = TestingSessionLocal()
    try:
        reservation = db.get(DocumentHash, ("test-tenant", hashlib.sha256(content).hexdigest()))
        assert reservation is not None
        assert reservation.document_id == first.json()["accepted"][0]["id"]
    finally:
        db.close()


def test_allow_duplicate_upload_option_remains_supported(client):
    content = _make_pdf_invoice("DUP-ALLOW-001", "Duplicate Allowed Supplier")
    first = client.post(
        "/api/documents/upload",
        files=[("files", ("duplicate.pdf", content, "application/pdf"))],
        params={"allow_duplicate": "true"},
    )
    second = client.post(
        "/api/documents/upload",
        files=[("files", ("duplicate-copy.pdf", content, "application/pdf"))],
        params={"allow_duplicate": "true"},
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert len(first.json()["accepted"]) == 1
    assert len(second.json()["accepted"]) == 1
    assert second.json()["rejected"] == []


def test_hybrid_search_preserves_keyword_hits_without_embeddings(client, monkeypatch):
    from conftest import TestingSessionLocal
    from app.models import Document
    import app.api.routes as routes_module
    from app.core.auth import get_current_user
    from app.main import app

    user = app.dependency_overrides[get_current_user]()
    document = Document(
        id="hybrid-null-vector", original_filename="office-keyword.pdf",
        stored_filename="hybrid-null-vector.pdf", file_type="pdf", mime_type="application/pdf",
        file_size=10, sha256="a" * 64, tenant_id=user.tenant_id, owner_id=user.id,
        status="completed", extracted_text="Invoice for rare-keyword-staplers",
        extracted_data={"invoice_number": "HYB-NULL", "supplier_name": "Office Supplies",
                        "customer_name": "Buyer", "total": 12.0, "currency": "USD", "line_items": []},
        embedding=None,
    )
    with TestingSessionLocal() as db:
        db.add(document)
        db.commit()
    monkeypatch.setattr(routes_module, "create_embedding", lambda _text: [1.0, 0.0])
    result = client.get("/api/search", params={"q": "rare-keyword-staplers", "mode": "hybrid"})
    assert result.status_code == 200
    assert any(item["id"] == "hybrid-null-vector" for item in result.json()["results"])


def test_reprocess_preserves_manual_overrides_and_records_snapshot(client, run_queued_jobs):
    content = _make_pdf_invoice("REPROCESS-OVERRIDE", "Original Supplier")
    upload = client.post("/api/documents/upload", files=[("files", ("reprocess-override.pdf", content, "application/pdf"))])
    document_id = upload.json()["accepted"][0]["id"]
    run_queued_jobs()
    before = client.get(f"/api/documents/{document_id}/result").json()
    correction = client.patch(f"/api/documents/{document_id}/corrections", json={
        "expected_version": before["version"], "fields": {"supplier_name": "Human Approved Supplier"}
    })
    assert correction.status_code == 200
    queued = client.post(f"/api/documents/{document_id}/reprocess")
    assert queued.status_code == 202
    run_queued_jobs()
    after = client.get(f"/api/documents/{document_id}/result").json()
    assert after["extracted_data"]["supplier_name"] == "Human Approved Supplier"
    events = client.get(f"/api/documents/{document_id}/history").json()
    snapshot = next(event for event in events if event["event_type"] == "reprocess_snapshot")
    assert snapshot["details"]["before"]["supplier_name"] == "Human Approved Supplier"


def test_first_admin_setup_is_one_time_and_assigns_legacy_documents(client):
    from conftest import TestingSessionLocal
    from app.models import Tenant, User, SetupState
    from app.core.auth import get_current_user
    from app.main import app
    from app.models import Document

    # Simulate a legacy local database containing documents but no new auth tables.
    with TestingSessionLocal() as db:
        db.query(SetupState).delete()
        db.query(User).delete()
        db.query(Tenant).delete()
        db.add(Document(
            id="legacy-unowned-document", original_filename="legacy.pdf",
            stored_filename="legacy-unowned.pdf", file_type="pdf", mime_type="application/pdf",
            file_size=1, sha256="b" * 64, status="completed", extracted_data={"invoice_number": "LEGACY-1"},
        ))
        db.commit()

    override = app.dependency_overrides.pop(get_current_user, None)
    try:
        status_before = client.get("/api/auth/setup-status")
        assert status_before.status_code == 200
        assert status_before.json()["setup_required"] is True
        created = client.post("/api/auth/setup", json={
            "email": "first-admin@example.invalid",
            "password": "a-very-long-test-password",
            "tenant_name": "Legacy Workspace",
        })
        assert created.status_code == 201
        assert created.json()["user"]["role"] == "admin"
        assert client.post("/api/auth/setup", json={
            "email": "second-admin@example.invalid",
            "password": "another-long-test-password",
        }).status_code == 409
        with TestingSessionLocal() as db:
            legacy = db.get(Document, "legacy-unowned-document")
            assert legacy is not None
            assert legacy.tenant_id == created.json()["user"]["tenant_id"]
            assert legacy.owner_id == created.json()["user"]["id"]
    finally:
        if override is not None:
            app.dependency_overrides[get_current_user] = override


def test_worker_reconciles_completed_document_without_reprocessing(client, run_queued_jobs):
    from conftest import TestingSessionLocal
    from datetime import timedelta
    from app.models import Document, ProcessingJob, ProcessingEvent, utcnow
    from app.worker import recover_expired_jobs

    content = _make_pdf_invoice("RECOVER-COMPLETED", "Recovery Supplier")
    uploaded = client.post("/api/documents/upload", files=[("files", ("recover-completed.pdf", content, "application/pdf"))])
    document_id = uploaded.json()["accepted"][0]["id"]
    run_queued_jobs()
    with TestingSessionLocal() as db:
        job = db.query(ProcessingJob).filter_by(document_id=document_id).one()
        job.status = "running"
        job.worker_id = "stale-worker"
        job.locked_at = utcnow() - timedelta(seconds=300)
        db.commit()
        before_events = db.query(ProcessingEvent).filter_by(document_id=document_id, event_type="processing_completed").count()
        recovered = recover_expired_jobs(db, lease_timeout_seconds=120)
        assert recovered == 1
        db.refresh(job)
        document = db.get(Document, document_id)
        assert job.status == "completed"
        assert document.status == "completed"
        after_events = db.query(ProcessingEvent).filter_by(document_id=document_id, event_type="processing_completed").count()
        assert after_events == before_events


def test_document_stats_counts_all_matching_records_not_just_current_page(client):
    from conftest import TestingSessionLocal
    from app.models import Document

    db = TestingSessionLocal()
    try:
        for index, state in enumerate(("completed", "completed", "failed", "pending"), start=1):
            db.add(Document(
                id=f"stats-{index}", original_filename=f"stats-{index}.csv",
                stored_filename=f"stats-{index}.csv", file_type="csv", mime_type="text/csv",
                file_size=10, sha256=f"{index:064x}", tenant_id="test-tenant",
                owner_id="test-admin", status=state,
            ))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/documents/stats")
    assert response.status_code == 200
    assert response.json() == {"total": 4, "completed": 2, "queued": 1, "failed": 1}


def test_duplicate_upload_is_rejected_across_owners_within_same_tenant(client):
    import hashlib
    from conftest import TestingSessionLocal
    from app.models import Document, User

    pdf = fitz.open()
    pdf.new_page()
    content = pdf.tobytes()
    pdf.close()
    digest = hashlib.sha256(content).hexdigest()

    db = TestingSessionLocal()
    try:
        db.add(User(
            id="test-reviewer", tenant_id="test-tenant", email="reviewer@example.invalid",
            password_hash="unused-test-hash", role="reviewer", is_active=True,
        ))
        db.flush()
        db.add(Document(
            id="owned-by-reviewer", original_filename="private.pdf", stored_filename="private.pdf",
            file_type="pdf", mime_type="application/pdf", file_size=len(content), sha256=digest,
            tenant_id="test-tenant", owner_id="test-reviewer", status="completed",
        ))
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/documents/upload",
        files=[("files", ("duplicate.pdf", content, "application/pdf"))],
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] == []
    assert payload["rejected"][0]["reason"] == "Duplicate content already exists in this workspace"
    assert "owned-by-reviewer" not in payload["rejected"][0]["reason"]


def test_delete_document_cors_preflight_is_allowed(client):
    response = client.options(
        "/api/documents/example-id",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert response.status_code == 200
    assert "DELETE" in response.headers.get("access-control-allow-methods", "")


def test_delete_document_database_failure_restores_original_file(client, run_queued_jobs, monkeypatch):
    from conftest import TestingSessionLocal
    from app.core.config import settings
    from app.models import Document
    from sqlalchemy.orm import Session

    content = _make_pdf_invoice("DELETE-ROLLBACK-1", "Rollback Delete Co")
    uploaded = client.post(
        "/api/documents/upload",
        files=[("files", ("restore-on-error.pdf", content, "application/pdf"))],
    )
    document_id = uploaded.json()["accepted"][0]["id"]
    assert run_queued_jobs() >= 1
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        original_path = settings.storage_path / document.stored_filename
        assert original_path.is_file()

    def fail_commit(_self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.delete(f"/api/documents/{document_id}")
    assert response.status_code == 500
    assert original_path.is_file()
    with TestingSessionLocal() as db:
        assert db.get(Document, document_id) is not None
def test_dotted_invoice_date_is_normalized_persisted_and_searchable(
    client, run_queued_jobs
):
    from conftest import TestingSessionLocal
    from app.models import Document

    pdf = fitz.open()
    page = pdf.new_page()

    page.insert_textbox(
        (50, 50, 550, 400),
        """Invoice Number: DATE-DOT-3010
Invoice Date: 30.10.2026
Supplier: Date Format Supplies
Customer: Example Buyer
Subtotal: 100.00
Tax: 15.00
Total: 115.00
Currency: USD"""
    )

    content = pdf.tobytes()
    pdf.close()

    uploaded = client.post(
        "/api/documents/upload",
        files=[
            ("files", ("dotted-date-invoice.pdf", content, "application/pdf"))
        ],
    )

    assert uploaded.status_code == 202
    document_id = uploaded.json()["accepted"][0]["id"]

    assert run_queued_jobs() >= 1

    result = client.get(f"/api/documents/{document_id}/result")

    assert result.status_code == 200
    assert result.json()["extracted_data"]["invoice_date"] == "2026-10-30"

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.invoice_date_iso == "2026-10-30"

    search = client.get(
        "/api/search",
        params={
            "date_from": "2026-10-30",
            "date_to": "2026-10-30",
        },
    )

    assert search.status_code == 200
    assert any(
        item["id"] == document_id
        for item in search.json()["results"]
    )
def test_keyword_search_finds_product_description_in_line_items(client):
    from conftest import TestingSessionLocal
    from app.models import Document
    from app.core.auth import get_current_user
    from app.main import app

    user = app.dependency_overrides[get_current_user]()

    document = Document(
        id="line-item-keyword-001",
        original_filename="line-item-only.pdf",
        stored_filename="line-item-keyword-001.pdf",
        file_type="pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256="b" * 64,
        tenant_id=user.tenant_id,
        owner_id=user.id,
        status="completed",
        extracted_text="Invoice record with no product description.",
        extracted_data={
            "invoice_number": "LINE-KEYWORD-001",
            "supplier_name": "Example Supplies",
            "customer_name": "Example Buyer",
            "total": 50.0,
            "currency": "USD",
            "line_items": [
                {
                    "description": "Quantum Blue Widget",
                    "quantity": 2,
                    "unit_price": 25.0,
                    "amount": 50.0,
                }
            ],
        },
        embedding=None,
    )

    with TestingSessionLocal() as db:
        db.add(document)
        db.commit()

    response = client.get(
        "/api/search",
        params={"q": "Quantum Blue Widget", "mode": "keyword"},
    )

    assert response.status_code == 200
    results = response.json()["results"]

    assert any(
        item["id"] == "line-item-keyword-001"
        for item in results
    )
def test_manual_corrections_are_preserved_in_long_document_embedding(
    client, monkeypatch
):
    from conftest import TestingSessionLocal
    from app.models import Document
    from app.core.auth import get_current_user
    from app.main import app
    import app.api.routes as routes_module

    user = app.dependency_overrides[get_current_user]()

    document = Document(
        id="embedding-correction-long-001",
        original_filename="long-invoice.pdf",
        stored_filename="embedding-correction-long-001.pdf",
        file_type="pdf",
        mime_type="application/pdf",
        file_size=10000,
        sha256="c" * 64,
        tenant_id=user.tenant_id,
        owner_id=user.id,
        status="completed",
        extracted_text="ORIGINAL_SOURCE_MARKER " + ("x" * 10000),
        extracted_data={
            "invoice_number": "EMBED-001",
            "invoice_date": "2026-10-30",
            "supplier_name": "Original Supplier",
            "customer_name": "Example Buyer",
            "subtotal": 100.0,
            "tax": 15.0,
            "total": 115.0,
            "currency": "USD",
            "line_items": [],
        },
        embedding=None,
    )

    with TestingSessionLocal() as db:
        db.add(document)
        db.commit()

    current = client.get(
        "/api/documents/embedding-correction-long-001/result"
    )
    assert current.status_code == 200

    captured_embeddings = []

    def fake_create_embedding(text):
        captured_embeddings.append(text)
        return [0.1, 0.2]

    monkeypatch.setattr(
        routes_module,
        "create_embedding",
        fake_create_embedding,
    )

    corrected = client.patch(
        "/api/documents/embedding-correction-long-001/corrections",
        json={
            "expected_version": current.json()["version"],
            "fields": {
                "supplier_name": "Corrected Supplier Marker",
                "line_items": [
                    {
                        "description": "Corrected Product Marker",
                        "quantity": 2,
                        "unit_price": 50,
                        "amount": 100,
                    }
                ],
            },
            "corrected_by": "pytest",
        },
    )

    assert corrected.status_code == 200
    assert len(captured_embeddings) == 1

    embedding_text = captured_embeddings[0]

    assert len(embedding_text) <= 8000
    assert embedding_text.startswith("search_document:")
    assert "Corrected Supplier Marker" in embedding_text
    assert "Corrected Product Marker" in embedding_text
    assert "ORIGINAL_SOURCE_MARKER" in embedding_text

def test_ocr_confidence_is_persisted_and_returned(
    client, run_queued_jobs, monkeypatch
):
    from conftest import TestingSessionLocal
    from app.models import Document
    import app.services.jobs as jobs_module

    def fake_process_document(_path):
        text = """Invoice Number: OCR-CONF-001
Invoice Date: 2026-10-30
Supplier: OCR Test Supplies
Customer: Example Buyer
Subtotal: 100.00
Tax: 15.00
Total: 115.00
Currency: USD"""

        metadata = {
            "kind": "pdf",
            "ocr_mean_confidence": 87.5,
            "low_ocr_confidence": False,
        }
        return text, 1, metadata

    monkeypatch.setattr(
        jobs_module, "process_document", fake_process_document
    )
    monkeypatch.setattr(
        jobs_module, "create_embedding", lambda _text: None
    )

    content = _make_pdf_invoice("OCR-CONF-001", "OCR Test Supplies")

    uploaded = client.post(
        "/api/documents/upload",
        files=[("files", ("ocr-confidence.pdf", content, "application/pdf"))],
    )

    assert uploaded.status_code == 202
    document_id = uploaded.json()["accepted"][0]["id"]

    assert run_queued_jobs() >= 1

    result = client.get(f"/api/documents/{document_id}/result")

    assert result.status_code == 200
    assert result.json()["ocr_confidence"] == 87.5

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.ocr_confidence == 87.5

def test_legacy_database_migration_adds_ocr_confidence_without_data_loss():
    from sqlalchemy import create_engine, inspect, text
    from app.db import run_compatibility_migrations

    engine = create_engine("sqlite://")

    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE documents (
                    id VARCHAR(36) PRIMARY KEY,
                    sha256 VARCHAR(64) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    created_at DATETIME NOT NULL,
                    extracted_data JSON
                )
            """))

            connection.execute(text("""
                INSERT INTO documents (
                    id, sha256, status, created_at, extracted_data
                ) VALUES (
                    'legacy-doc-001',
                    'a123456789',
                    'completed',
                    CURRENT_TIMESTAMP,
                    '{"invoice_number":"LEGACY-1",
                      "invoice_date":"2026-10-30",
                      "supplier_name":"Legacy Supplies"}'
                )
            """))

        # Simulate an upgrade from the older database schema.
        run_compatibility_migrations(engine)

        columns = {
            column["name"]
            for column in inspect(engine).get_columns("documents")
        }

        assert "ocr_confidence" in columns

        with engine.connect() as connection:
            row = connection.execute(text("""
                SELECT id, status, ocr_confidence, invoice_date_iso,
                       invoice_number_norm, supplier_name_norm
                FROM documents
                WHERE id = 'legacy-doc-001'
            """)).one()

        assert row.id == "legacy-doc-001"
        assert row.status == "completed"
        assert row.ocr_confidence is None
        assert row.invoice_date_iso == "2026-10-30"
        assert row.invoice_number_norm == "legacy-1"
        assert row.supplier_name_norm == "legacy supplies"

        # Running the migration again must remain safe.
        run_compatibility_migrations(engine)

        assert "ocr_confidence" in {
            column["name"]
            for column in inspect(engine).get_columns("documents")
        }

    finally:
        engine.dispose()
