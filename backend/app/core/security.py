import secrets
from fastapi import Header, HTTPException, status
from app.core.config import settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Local-only developer bypass; production must configure a shared key.

    A browser-shipped shared key is only suitable for a local demo, not production.
    """
    configured_key = settings.api_key.strip()
    if not configured_key:
        if settings.app_env.lower() == "development":
            return
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key is not configured")
    if x_api_key is None or not secrets.compare_digest(x_api_key, configured_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key")
