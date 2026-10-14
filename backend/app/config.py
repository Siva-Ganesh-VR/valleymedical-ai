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

    # LLM provider switch: gemini (default) | anthropic | mock.
    # If left unset and GEMINI_API_KEY is missing, the offline mock is used. If set explicitly, the key is required.
    llm_provider: str = "gemini"
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-sonnet-5-5"
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = "gemini-3.5-flash-lite"
    # Gemini "thinking" tokens count against the output limit, so this is larger than llm_max_tokens.
    gemini_max_tokens: int = 8192
    gemini_temperature: float | None = None  # None = model default
    llm_max_retries: int = 3
    # Requests per minute across the whole app, to stay under the provider's quota (429 errors).
    # Check your key's limit in the provider console. 0 disables throttling. The mock is never throttled.
    llm_requests_per_minute: int = 10
    # Longest wait honoured when the provider asks us to retry later (seconds).
    llm_max_retry_wait_seconds: float = 60.0
    # Spaces model calls out to stay under the provider's per-minute quota (429 errors otherwise).
    # Check your key's limit in the provider console. 0 disables throttling.
    llm_requests_per_minute: int = 10
    # Longest wait honoured when the provider says "retry after N seconds".
    llm_max_retry_wait_seconds: float = 60.0
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

    # AI gateway (WBS N3/N10). Prices are per million tokens, from your provider's price page.
    # Leave unset to show token counts only.
    llm_price_input_per_mtok: float | None = None
    llm_price_output_per_mtok: float | None = None
    # Monthly token budget across all workflows. Calls are blocked (and go to the exception queue)
    # once it is used up. 0 or None disables the budget.
    llm_monthly_token_budget: int | None = 5_000_000

    acceptance_testset: Path = FIXTURES_DIR / "acceptance_testset.json"

    # Hosting (single-service deployments such as Render's free tier)
    # Folder with the built React app. When set, the API also serves the UI from the same URL.
    static_dir: Path | None = None
    # When set, every page and API call needs this password (browser sign-in prompt, any username).
    # Strongly recommended on any public URL: otherwise anyone can use the app and your AI quota.
    demo_password: str | None = None

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]
