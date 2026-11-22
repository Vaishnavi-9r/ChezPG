
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load the .env file from the backend folder.
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEVELOPMENT_SAMPLE_MARKER_PREFIX = "[chezpg-dev-sample:v1:"


class Settings(BaseSettings):
    app_name: str = "ChezPG API"
    database_url: str
    app_env: Literal["development", "production", "test"] = "production"
    development_sample_search_enabled: bool = False
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default=["http://localhost:8081", "http://127.0.0.1:8081"]
    )
    owner_token_secret: str | None = None
    access_token_expiry_minutes: int = Field(default=30, gt=0, le=1440)
    availability_stale_hours: int = Field(default=168, gt=0, le=8760)
    photo_storage_dir: Path = BACKEND_DIR / "private_uploads"
    photo_max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    photo_max_per_pg: int = Field(default=10, gt=0, le=100)
    verification_storage_dir: Path = BACKEND_DIR / "private_verification_uploads"
    verification_max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_development_sample_search(self):
        if not self.development_sample_search_enabled:
            return self
        if self.app_env != "development":
            raise ValueError(
                "Development sample search requires APP_ENV=development."
            )
        try:
            database_url = urlsplit(self.database_url)
            database_port = database_url.port
        except ValueError:
            database_port = None
            database_url = urlsplit("")
        if (
            database_url.scheme != "postgresql+psycopg"
            or database_url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or database_port != 5433
            or database_url.path.strip("/") != "chezpg"
        ):
            raise ValueError(
                "Development sample search is restricted to the local chezpg "
                "PostgreSQL database on host port 5433."
            )
        return self


settings = Settings()
