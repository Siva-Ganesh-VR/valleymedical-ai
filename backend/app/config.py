"""Application settings, loaded from environment variables (prefix VM_) or a .env file."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="VM_", extra="ignore", populate_by_name=True
    )

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'poc.db'}"

    # LLM: "auto" uses Anthropic when ANTHROPIC_API_KEY is set, otherwise the offline mock.
    llm_provider: str = "auto"  # auto | anthropic | mock
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-sonnet-5-5"
    llm_max_retries: int = 3
    llm_timeout_seconds: float = 60.0
    llm_max_tokens: int = 2048

    # Billing agent business settings (placeholders until Valley Medical approves real rules).
    classification_confidence_threshold: float = 0.80
    unworked_after_days: int = 30
    max_draft_attempts: int = 3

    # Fixes "today" for repeatable demos and tests. None means the real date.
    as_of_date: date | None = None

    meditab_fixture: Path = FIXTURES_DIR / "meditab_mock.json"
    billing_fixture: Path = FIXTURES_DIR / "billing_mock.json"

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]
