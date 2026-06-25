from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import EmailStr, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME: str = "Blade Rocking & Creep Test Management System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: Literal["dev", "development", "staging", "prod", "production"] = "dev"

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    API_V1_STR: str = "/api/v1"

    # ------------------------------------------------------------------
    # Security / JWT
    # ------------------------------------------------------------------
    SECRET_KEY: str = secrets.token_urlsafe(64)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DATABASE_URL: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/blade_rocking"
    )

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    REDIS_URL: RedisDsn = RedisDsn("redis://localhost:6379/0")

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    CORS_ORIGINS: list[str] = []

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list) -> list[str]:
        if isinstance(value, str):
            v = value.strip()
            if v.startswith("["):
                import json
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return list(value)

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------
    OCR_PROVIDER: str = "paddleocr"  # mock | tesseract | paddleocr

    # ------------------------------------------------------------------
    # File uploads
    # ------------------------------------------------------------------
    MAX_FILE_SIZE_MB: int = 10
    UPLOAD_DIR: str = "/app/uploads"

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def ocr_scan_dir(self) -> str:
        return f"{self.UPLOAD_DIR}/ocr_scans"

    # ------------------------------------------------------------------
    # SMTP (optional — all fields can be omitted)
    # ------------------------------------------------------------------
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_TLS: bool = True
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_ADDRESS: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @property
    def smtp_enabled(self) -> bool:
        return all(
            [self.SMTP_HOST, self.SMTP_USER, self.SMTP_PASSWORD, self.EMAILS_FROM_ADDRESS]
        )

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def database_url_str(self) -> str:
        return str(self.DATABASE_URL)

    @property
    def redis_url_str(self) -> str:
        return str(self.REDIS_URL)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
