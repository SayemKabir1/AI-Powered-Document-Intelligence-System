from __future__ import annotations

import hmac
import re
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import hash_password, verify_password, set_session_cookies, clear_session_cookies, get_current_user, require_admin
from app.core.config import settings
from app.db import get_db
from app.models import Tenant, User, Document, SetupState

router = APIRouter(prefix="/api/auth", tags=["authentication"])

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    tenant_name: str | None = Field(default="My workspace", max_length=160)
    bootstrap_token: str | None = Field(default=None, max_length=256)

class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(default="reviewer", pattern="^(admin|reviewer)$")


def _normalized_email(value: str) -> str:
    normalized = value.strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
        raise HTTPException(status_code=422, detail="A valid email address is required")
    return normalized


def _public_user(user: User):
    return {"id": user.id, "email": user.email, "role": user.role, "tenant_id": user.tenant_id}


def _ensure_setup_state(db: Session) -> SetupState:
    state = db.get(SetupState, 1)
    if state is not None:
        return state
    # Existing installations may already have user records from a prior setup.
    has_users = bool(db.scalar(select(func.count()).select_from(User)) or 0)
    db.add(SetupState(id=1, initialized=has_users))
    try:
        db.commit()
    except IntegrityError:
        # Another process may have inserted the singleton row first.
        db.rollback()
    state = db.get(SetupState, 1)
    if state is None:
        raise HTTPException(status_code=503, detail="Workspace setup state is unavailable")
    return state


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)):
    state = _ensure_setup_state(db)
    return {"setup_required": not state.initialized, "bootstrap_token_required": settings.app_env.lower() != "development"}


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def first_admin_setup(payload: Credentials, response: Response, db: Session = Depends(get_db)):
    state = _ensure_setup_state(db)
    if state.initialized:
        raise HTTPException(status_code=409, detail="Initial administrator has already been created")
    if settings.app_env.lower() != "development":
        configured = settings.bootstrap_token.strip()
        supplied = (payload.bootstrap_token or "").strip()
        if not configured or not supplied or not hmac.compare_digest(configured, supplied):
            raise HTTPException(status_code=403, detail="A valid bootstrap token is required for initial production setup")
    email = _normalized_email(payload.email)
    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Atomically reserve one-time setup. The conditional update prevents two
    # simultaneous setup requests in different API workers from creating
    # separate first-admin tenants. The flag change rolls back if creation fails.
    reserved = db.execute(
        update(SetupState).where(SetupState.id == 1, SetupState.initialized.is_(False))
        .values(initialized=True)
    )
    if reserved.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Initial administrator has already been created")
    tenant = Tenant(id=str(uuid.uuid4()), name=(payload.tenant_name or "My workspace").strip() or "My workspace")
    user = User(id=str(uuid.uuid4()), tenant_id=tenant.id, email=email, password_hash=password_hash, role="admin", is_active=True)
    try:
        db.add(tenant)
        db.add(user)
        db.flush()
        # Preserve existing local documents by assigning previously unowned rows to
        # the first workspace administrator; no document or file is deleted.
        db.execute(update(Document).where(Document.tenant_id.is_(None)).values(tenant_id=tenant.id, owner_id=user.id))
        # Reserve existing file hashes by workspace without removing any legacy
        # duplicate document rows or original storage files.
        db.execute(text(
            "INSERT INTO document_hashes (tenant_id, sha256, document_id, created_at) "
            "SELECT :tenant_id, sha256, MIN(id), CURRENT_TIMESTAMP FROM documents "
            "WHERE tenant_id = :tenant_id GROUP BY sha256 "
            "ON CONFLICT (tenant_id, sha256) DO NOTHING"
        ), {"tenant_id": tenant.id})
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise
    set_session_cookies(response, user)
    return {"user": _public_user(user)}


@router.post("/login")
def login(payload: Credentials, response: Response, db: Session = Depends(get_db)):
    email = _normalized_email(payload.email)
    user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    set_session_cookies(response, user)
    return {"user": _public_user(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"user": _public_user(user)}


@router.post("/logout")
def logout(response: Response, _user: User = Depends(get_current_user)):
    clear_session_cookies(response)
    return {"logged_out": True}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_workspace_user(payload: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    email = _normalized_email(payload.email)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    try:
        encoded = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = User(id=str(uuid.uuid4()), tenant_id=admin.tenant_id, email=email, password_hash=encoded, role=payload.role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user": _public_user(user)}


@router.get("/users")
def list_workspace_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    users = db.scalars(select(User).where(User.tenant_id == admin.tenant_id).order_by(User.created_at.asc())).all()
    return {"users": [_public_user(user) for user in users]}
