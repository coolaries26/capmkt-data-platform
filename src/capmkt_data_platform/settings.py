"""Typed settings loaded from environment variables and the project's .env file.

Relative paths are resolved against the project root, NOT the current working
directory. That makes the CLI behave the same when launched from VS Code, a
terminal, or an Airflow task.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/capmkt_data_platform/settings.py -> parents[2] is the repository root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Priority: init args > real environment variables > .env file
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env also holds PG* values used by other tools
    )

    data_dir: Path = Path("data")
    datasets_file: Path = Path("config/datasets.yml")

    http_timeout_seconds: float = 60.0
    http_max_attempts: int = 3
    http_backoff_seconds: float = 2.0
    request_pause_seconds: float = 1.0  # polite delay between downloads in backfill

    @field_validator("data_dir", "datasets_file")
    @classmethod
    def _make_absolute(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @property
    def landing_dir(self) -> Path:
        return self.data_dir / "landing"


def get_settings() -> Settings:
    """Build fresh settings each call (cheap, and keeps tests free of caching)."""
    return Settings()
