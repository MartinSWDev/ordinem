"""Runtime configuration, loaded from the environment (see .env.example).

Nothing here is hardcoded — every value comes from env / .env so the same code
runs locally, on the home PC, and against the Coolify Postgres unchanged.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database. Points at whichever Postgres holds *this* deployment's data:
    # a local instance on the work Mac for the `work` schema (keeps work ticket
    # data on the work machine), or the shared Coolify Postgres for
    # personal/shared data. See the README "Deployment & data residency".
    database_url: str = "postgresql://ordinem:ordinem@localhost:5433/ordinem"
    db_schema: str = "work"

    # Jira
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_acceptance_criteria_field: str = ""

    # Calendar (read-only private iCal feeds, comma-separated)
    calendar_ics_urls: str = ""

    @property
    def calendar_urls(self) -> list[str]:
        return [url.strip() for url in self.calendar_ics_urls.split(",") if url.strip()]

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""  # blank = SDK default (api.anthropic.com)
    review_model: str = "claude-opus-4-8"

    # Qwen fallback
    qwen_proxy_url: str = ""

    # Server
    host: str = "127.0.0.1"
    port: int = 8787

    @property
    def jira_configured(self) -> bool:
        return bool(self.jira_base_url and self.jira_email and self.jira_api_token)

    @property
    def qwen_configured(self) -> bool:
        return bool(self.qwen_proxy_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
