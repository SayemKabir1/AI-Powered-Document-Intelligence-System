from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI-Powered Document Intelligence System"
    app_env: str = "development"
    database_url: str = "sqlite:///./document_intelligence.db"
    storage_dir: str = "./storage"
    max_upload_mb: int = 50
    max_pdf_pages: int = 1200
    max_image_pixels: int = 50_000_000
    max_spreadsheet_rows: int = 200_000
    max_spreadsheet_sheets: int = 100
    ocr_timeout_seconds: float = 30.0
    cors_origins: str = "http://localhost:5173"
    api_key: str = ""  # Legacy service key; never ship this to the browser.
    session_secret: str = ""
    demo_mode: bool = False
    demo_user_email: str = "public-demo@local.invalid"
    bootstrap_token: str = ""
    session_ttl_seconds: int = 43200
    upload_request_mb: int = 100
    upload_concurrency: int = 4
    min_semantic_similarity: float = 0.55
    rate_limit_per_minute: int = 120
    ollama_enabled: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_timeout_seconds: float = 12.0
    worker_poll_seconds: float = 0.75
    worker_retry_delay_seconds: float = 2.0
    worker_lease_timeout_seconds: int = 120
    worker_heartbeat_seconds: float = 30.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        return path if path.is_absolute() else (Path.cwd() / path).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
