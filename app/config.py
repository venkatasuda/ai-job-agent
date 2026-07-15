"""
app/config.py — Centralized, type-safe configuration
======================================================
Uses Pydantic Settings v2 for:
  - Environment variable injection (12-factor app)
  - Type validation at startup (fail fast)
  - Nested config sections
  - .env file support

Priority order: env vars > .env file > config.yaml defaults
"""

from __future__ import annotations

import yaml
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import AnyUrl, EmailStr, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Sub-models ───────────────────────────────────────────────────────────────

class ProfileSettings(BaseSettings):
    name: str = "Job Seeker"
    email: str = "user@example.com"
    resume_path: Path = Path("resume.txt")
    linkedin_url: str = ""
    location: str = "United States"
    remote_ok: bool = True


class AISettings(BaseSettings):
    provider: Literal["openai", "gemini", "ollama"] = "openai"
    model: str = "gpt-4o-mini"
    min_match_score: int = Field(70, ge=0, le=100)
    openai_api_key: Optional[SecretStr] = Field(None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[SecretStr] = Field(None, alias="GEMINI_API_KEY")
    cover_letter_threshold: int = Field(70, ge=0, le=100)
    company_research_threshold: int = Field(78, ge=0, le=100)
    interview_prep_threshold: int = Field(80, ge=0, le=100)
    salary_estimate: bool = True

    model_config = SettingsConfigDict(populate_by_name=True)

    @field_validator("min_match_score", "cover_letter_threshold",
                     "company_research_threshold", "interview_prep_threshold")
    @classmethod
    def validate_threshold(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError(f"Threshold must be 0–100, got {v}")
        return v

    def get_api_key(self) -> str:
        """Return the active provider's API key as plain string."""
        if self.provider == "openai" and self.openai_api_key:
            return self.openai_api_key.get_secret_value()
        if self.provider == "gemini" and self.gemini_api_key:
            return self.gemini_api_key.get_secret_value()
        return ""


class EmailAlertSettings(BaseSettings):
    enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_email: str = ""
    sender_password: Optional[SecretStr] = Field(None, alias="EMAIL_PASSWORD")
    recipient_email: str = ""
    min_score_to_alert: int = 70
    include_followup_reminders: bool = True

    model_config = SettingsConfigDict(populate_by_name=True)


class TelegramSettings(BaseSettings):
    enabled: bool = False
    bot_token: Optional[SecretStr] = Field(None, alias="TELEGRAM_BOT_TOKEN")
    chat_id: str = Field("", alias="TELEGRAM_CHAT_ID")
    min_score_to_alert: int = 75

    model_config = SettingsConfigDict(populate_by_name=True)


class WhatsAppSettings(BaseSettings):
    enabled: bool = False
    provider: Literal["callmebot", "twilio"] = "callmebot"
    phone_number: str = ""
    callmebot_api_key: Optional[SecretStr] = None
    min_score_to_alert: int = 80


class AlertsSettings(BaseSettings):
    email: EmailAlertSettings = EmailAlertSettings()
    telegram: TelegramSettings = TelegramSettings()
    whatsapp: WhatsAppSettings = WhatsAppSettings()


class DatabaseSettings(BaseSettings):
    path: Path = Path("jobs.db")
    dedupe_window_days: int = 30


class ScheduleSettings(BaseSettings):
    interval_minutes: int = Field(60, ge=1)
    run_immediately: bool = True


class NewGradSettings(BaseSettings):
    enabled: bool = True
    degree: str = "Masters"
    field: str = "Computer Science"
    school: str = ""
    school_tier: Literal["Top-10", "Top-50", "Other"] = "Top-50"
    graduation_year: int = 2024
    is_international: bool = False


class VisaFilterSettings(BaseSettings):
    exclude_no_sponsor: bool = False
    require_sponsorship: bool = False


class DailyRoutineSettings(BaseSettings):
    enabled: bool = True
    daily_application_target: int = Field(10, ge=1)
    morning_briefing_hour: int = Field(8, ge=0, le=23)
    evening_summary_hour: int = Field(18, ge=0, le=23)
    streak_reminder: bool = True


class NotionSettings(BaseSettings):
    enabled: bool = False
    token: Optional[SecretStr] = Field(None, alias="NOTION_TOKEN")
    database_id: str = ""
    min_score_to_sync: int = 70

    model_config = SettingsConfigDict(populate_by_name=True)


class AirtableSettings(BaseSettings):
    enabled: bool = False
    token: Optional[SecretStr] = Field(None, alias="AIRTABLE_TOKEN")
    base_id: str = ""
    table_name: str = "Job Applications"

    model_config = SettingsConfigDict(populate_by_name=True)


class IntegrationsSettings(BaseSettings):
    notion: NotionSettings = NotionSettings()
    airtable: AirtableSettings = AirtableSettings()


# ── Root Settings ─────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    """
    Root settings. Loads from config.yaml, then overrides with env vars.
    Usage:
        from app.config import get_settings
        cfg = get_settings()
        cfg.ai.model  # → "gpt-4o-mini"
    """
    profile: ProfileSettings = ProfileSettings()
    ai: AISettings = AISettings()
    alerts: AlertsSettings = AlertsSettings()
    database: DatabaseSettings = DatabaseSettings()
    schedule: ScheduleSettings = ScheduleSettings()
    new_grad: NewGradSettings = NewGradSettings()
    visa_filter: VisaFilterSettings = VisaFilterSettings()
    daily_routine: DailyRoutineSettings = DailyRoutineSettings()
    integrations: IntegrationsSettings = IntegrationsSettings()

    # Runtime flags
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    version: str = "3.0.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",  # AI__MODEL=gpt-4o sets ai.model
        extra="ignore",
    )

    @classmethod
    def from_yaml(cls, path: str | Path = "config.yaml") -> "Settings":
        """Load from YAML file, then apply env var overrides."""
        p = Path(path)
        if not p.exists():
            return cls()
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    def as_legacy_dict(self) -> dict:
        """Return config as plain dict for backward compat with v2 modules."""
        return self.model_dump(mode="json")


@lru_cache(maxsize=1)
def get_settings(config_path: str = "config.yaml") -> Settings:
    """Cached settings singleton — call once, reuse everywhere."""
    return Settings.from_yaml(config_path)


def reload_settings(config_path: str = "config.yaml") -> Settings:
    """Force reload (useful in tests or after config changes)."""
    get_settings.cache_clear()
    return get_settings(config_path)
