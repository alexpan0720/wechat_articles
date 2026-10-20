from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "衡正律师事务所"
    app_env: str = "development"
    secret_key: str = "development-secret-change-before-production"
    database_url: str = "sqlite:///./data/lawfirm.db"
    public_base_url: str = "http://127.0.0.1:8000"
    storage_dir: Path = Path("./data/storage")

    sync_adapter: str = "file"
    sync_feed_path: Path = Path("./examples/wechat_feed.json")
    sync_api_base_url: str | None = None
    sync_api_token: str | None = None
    sync_lookback_days: int = Field(default=30, ge=1, le=365)
    auto_publish: bool = True
    max_asset_bytes: int = 20 * 1024 * 1024

    admin_username: str = "admin"
    admin_password: str = "change-me-now"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def validate_production(self) -> None:
        if self.is_production and self.secret_key == "development-secret-change-before-production":
            raise RuntimeError("SECRET_KEY must be changed before production startup")
        if self.is_production and len(self.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must contain at least 32 characters in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()

