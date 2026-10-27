"""Service settings from environment variables (prefix SA_) or a .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SA_", extra="ignore")

    db_path: Path = ROOT / "data" / "support.db"
    config_path: Path | None = Field(None, description="workspace JSON: business hours, SLA, topics, prices")
    # Where scheduled syncs read from: "synthetic", "csv:<folder>" or "json:<file>". Empty disables the scheduler.
    sync_source: str = ""
    sync_interval_s: int = Field(0, ge=0)
    # Keys allowed to push data to POST /api/ingest. Empty list disables the endpoint.
    api_keys: list[SecretStr] = []
    max_ingest_bytes: int = Field(5_000_000, ge=1_000)
    allowed_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()
