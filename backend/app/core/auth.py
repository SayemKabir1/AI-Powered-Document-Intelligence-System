from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.models import User, Document


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    secret = settings.session_secret.strip()
    if not secret and settings.app_env.lower() == "development":
        secret = "local-development-only-change-before-network-use"
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Session signing secret is not configured")
    return secret.encode("utf-8")


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    iterations = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(iterations))
        return hmac.compare_digest(_b64(actual), expected)
    except (ValueError, TypeError):
        return False


def issue_session(user: User) -> tuple[str, str]:
    now = int(time.time())
    csrf = secrets.token_urlsafe(32)
    payload = {
        "sub": user.id,
        "tenant": user.tenant_id,
        "role": user.role,
        "iat": now,
        "exp": now + max(300, settings.session_ttl_seconds),
        "csrf": csrf,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}", csrf


def decode_session(token: str) -> dict[str, Any] | None:
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_unb64(body))
        if not isinstance(payload, dict) or int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def set_session_cookies(response, user: User) -> None:
    token, csrf = issue_session(user)
    secure = settings.app_env.lower() != "development"
    response.set_cookie("docintel_session", token, httponly=True, secure=secure, samesite="strict", max_age=settings.session_ttl_seconds, path="/")
    response.set_cookie("docintel_csrf", csrf, httponly=False, secure=secure, samesite="strict", max_age=settings.session_ttl_seconds, path="/")


def clear_session_cookies(response) -> None:
    secure = settings.app_env.lower() != "development"
    response.delete_cookie("docintel_session", path="/", secure=secure, httponly=True, samesite="strict")
    response.delete_cookie("docintel_csrf", path="/", secure=secure, httponly=False, samesite="strict")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    if settings.demo_mode:
        # Recruiter/demo deployment: all visitors share one explicitly seeded
        # demo workspace. This mode is intentionally not suitable for private data.
        demo_user = db.scalar(
            select(User).where(
                User.email == settings.demo_user_email,
                User.is_active.is_(True),
                User.role == "admin",
            )
        )
        if not demo_user:
            raise HTTPException(status_code=503, detail="Public demo workspace is not initialized")
        return demo_user

    token = request.cookies.get("docintel_session")
    payload = decode_session(token or "") if token else None
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user = db.get(User, str(payload.get("sub", "")))
    if not user or not user.is_active or user.tenant_id != payload.get("tenant"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        cookie_token = request.cookies.get("docintel_csrf", "")
        header_token = request.headers.get("X-CSRF-Token", "")
        claim_token = str(payload.get("csrf", ""))
        if not (cookie_token and header_token and hmac.compare_digest(cookie_token, claim_token) and hmac.compare_digest(header_token, claim_token)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return user


def document_scope(user: User):
    predicate = Document.tenant_id == user.tenant_id
    if user.role != "admin":
        predicate = predicate & (Document.owner_id == user.id)
    return predicate


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user
