import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import event

# Ensure test settings are loaded before importing application modules.
os.environ["APP_ENV"] = "development"
os.environ["DEMO_MODE"] = "false"
os.environ["OLLAMA_ENABLED"] = "false"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="docintel-test-")
os.environ["DATABASE_URL"] = "sqlite://"

from app.core.config import get_settings
get_settings.cache_clear()
from app.db import Base, get_db
from app.main import app, _rate_buckets
from app.models import Tenant, User
from app.core.auth import hash_password, get_current_user
import app.services.jobs as jobs_module

TEST_ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
@event.listens_for(TEST_ENGINE, "connect")
def _test_sqlite_pragmas(connection, _record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()
TestingSessionLocal = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)

@pytest.fixture()
def client():
    Base.metadata.create_all(bind=TEST_ENGINE)
    tenant = Tenant(id="test-tenant", name="Test workspace")
    test_user = User(id="test-admin", tenant_id=tenant.id, email="admin@example.invalid", password_hash=hash_password("test-password-long-enough"), role="admin", is_active=True)
    with TestingSessionLocal() as seed_db:
        if not seed_db.get(Tenant, tenant.id):
            seed_db.add(tenant)
            seed_db.add(test_user)
            seed_db.commit()
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    jobs_module.SessionLocal = TestingSessionLocal
    _rate_buckets.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    _rate_buckets.clear()
    Base.metadata.drop_all(bind=TEST_ENGINE)

@pytest.fixture()
def run_queued_jobs():
    """Drive the durable queue synchronously in tests without changing API behavior."""
    from app.worker import process_next_job

    def _run(max_jobs=50):
        count = 0
        while count < max_jobs and process_next_job(session_factory=TestingSessionLocal, worker_id="pytest-worker"):
            count += 1
        return count
    return _run
