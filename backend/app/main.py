import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from threading import Lock
import secrets
import uuid

from sqlalchemy import select

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.auth_routes import router as auth_router
from app.core.config import settings
from app.db import Base, SessionLocal, engine, run_compatibility_migrations
from app.models import Document, Tenant, User
from app.core.auth import hash_password
from app import models  # noqa: F401 ensure SQLAlchemy tables register

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

def ensure_demo_workspace() -> None:
    """Create a non-personal shared demo identity without replacing user data."""
    with SessionLocal() as db:
        demo_user = db.scalar(select(User).where(User.email == settings.demo_user_email))
        if demo_user is None:
            # Reuse an existing administrator's workspace when possible, otherwise
            # attach the demo identity to the first active workspace. Never merge tenants.
            workspace_user = db.scalar(
                select(User).where(User.is_active.is_(True), User.role == "admin")
                .order_by(User.created_at.asc()).limit(1)
            )
            if workspace_user is None:
                workspace_user = db.scalar(
                    select(User).where(User.is_active.is_(True))
                    .order_by(User.created_at.asc()).limit(1)
                )

            if workspace_user is not None:
                tenant_id = workspace_user.tenant_id
            else:
                tenant_id = str(uuid.uuid4())
                db.add(Tenant(id=tenant_id, name="Public Demo Workspace"))
                db.flush()

            demo_user = User(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                email=settings.demo_user_email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role="admin",
                is_active=True,
            )
            db.add(demo_user)
            db.flush()
        elif not demo_user.is_active or demo_user.role != "admin":
            raise RuntimeError("The configured public demo identity must be an active administrator")

        # Assign only legacy, unscoped records to this one workspace. Existing
        # tenant assignments and uploaded files are left untouched.
        legacy_documents = db.scalars(select(Document).where(Document.tenant_id.is_(None))).all()
        for document in legacy_documents:
            document.tenant_id = demo_user.tenant_id
            if document.owner_id is None:
                document.owner_id = demo_user.id
        unowned_demo_documents = db.scalars(
            select(Document).where(
                Document.tenant_id == demo_user.tenant_id,
                Document.owner_id.is_(None),
            )
        ).all()
        for document in unowned_demo_documents:
            document.owner_id = demo_user.id
        db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_compatibility_migrations(engine)
    if settings.demo_mode:
        ensure_demo_workspace()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    if settings.app_env.lower() != "development":
        if not settings.demo_mode:
            if len(settings.session_secret.strip()) < 32:
                raise RuntimeError("SESSION_SECRET must be configured with at least 32 characters outside development mode")
            if len(settings.bootstrap_token.strip()) < 24:
                raise RuntimeError("BOOTSTRAP_TOKEN must be configured with at least 24 characters outside development mode")
        if not settings.cors_origin_list or "*" in settings.cors_origin_list:
            raise RuntimeError("CORS_ORIGINS must contain explicit trusted origins outside development mode")
    yield


docs_enabled = settings.app_env.lower() == "development"
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Local-first invoice/document intelligence API",
    lifespan=lifespan,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

# Small in-process abuse guard. Deployments with multiple API replicas should also
# enforce distributed limits at the reverse proxy/API gateway.
_rate_lock = Lock()
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)

@app.middleware("http")
async def defensive_http_middleware(request: Request, call_next):
    now = time.monotonic()
    path = request.url.path
    if path.startswith("/api/"):
        # In production the backend is reachable only through the internal Nginx
        # network, which overwrites X-Real-IP. In development use the direct peer.
        forwarded_ip = request.headers.get("x-real-ip") if settings.app_env.lower() != "development" else None
        client_ip = forwarded_ip or (request.client.host if request.client else "unknown")
        key = f"{client_ip}:" + (
            "login" if path == "/api/auth/login" else
            "setup" if path == "/api/auth/setup" else
            "upload" if path.endswith("/documents/upload") else "api"
        )
        limit = (10 if key.endswith(":login") else 5 if key.endswith(":setup") else
                 20 if key.endswith(":upload") else max(30, settings.rate_limit_per_minute))
        with _rate_lock:
            bucket = _rate_buckets[key]
            while bucket and now - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= limit:
                return JSONResponse({"detail": "Rate limit exceeded; retry shortly."}, status_code=429, headers={"Retry-After": "60"})
            bucket.append(now)
            # Bound memory used by the in-process limiter if client IPs vary.
            if len(_rate_buckets) > 10_000:
                for stale_key in list(_rate_buckets.keys()):
                    stale = _rate_buckets[stale_key]
                    while stale and now - stale[0] > 60:
                        stale.popleft()
                    if not stale:
                        _rate_buckets.pop(stale_key, None)

    # Reject oversized declared request bodies before multipart parsing allocates memory.
    if path.endswith("/documents/upload"):
        content_length = request.headers.get("content-length")
        max_request = settings.upload_request_mb * 1024 * 1024
        if content_length and content_length.isdigit() and int(content_length) > max_request:
            return JSONResponse({"detail": f"Upload request exceeds the {settings.upload_request_mb} MB total limit."}, status_code=413)

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # Swagger UI in development requires its own inline assets; API/health
    # responses and production routes receive a restrictive no-render policy.
    if path not in {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}:
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
    if settings.app_env.lower() != "development":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

if not settings.demo_mode:
    app.include_router(auth_router)
app.include_router(router)

@app.get("/health", tags=["health"])
def health():
    # Do not expose environment names or configuration details to unauthenticated probes.
    return {"status": "ok", "service": settings.app_name}
