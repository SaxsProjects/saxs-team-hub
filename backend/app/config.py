"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field("development", description="development | test | production")

    database_url: str = "sqlite:///./teamhub.db"

    # Secrets: required in production (generate with `python -m app.cli generate-keys`).
    secret_key: str = "dev-only-insecure-secret-change-me"  # noqa: S105 - refused in production
    field_encryption_key: str = ""
    jobs_token: str = ""

    access_token_minutes: int = 60
    # Interactive API docs at /docs. Always on outside production; in production only when set,
    # e.g. so the founder can use the API from a browser until the frontend is built.
    enable_api_docs: bool = False
    require_admin_2fa: bool | None = None  # defaults to True in production

    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173"

    # Who gets notified about offer activity.
    admin_notify_email: str = ""

    # Outgoing email (Zoho Mail: smtppro.zoho.com / smtp.zoho.com, port 465, app-specific password).
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "SaxsProjects"

    company_name: str = "SaxsProjects"
    timezone: str = "Africa/Johannesburg"

    payout_delay_days: int = 7
    declined_retention_days: int = 365
    max_upload_mb: int = 10

    # Behind Render/most proxies the client IP is in X-Forwarded-For.
    trust_proxy: bool = True

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, value: str) -> str:
        # Neon/Heroku style URLs -> SQLAlchemy psycopg3 driver.
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def api_docs_enabled(self) -> bool:
        return self.enable_api_docs or not self.is_production

    @property
    def admin_2fa_required(self) -> bool:
        return self.is_production if self.require_admin_2fa is None else self.require_admin_2fa

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_pass)

    def check_production_ready(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.secret_key.startswith("dev-only") or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be set to a long random value")
        if not self.field_encryption_key:
            problems.append("FIELD_ENCRYPTION_KEY must be set")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL must point to PostgreSQL")
        if not self.smtp_configured:
            problems.append("SMTP_HOST, SMTP_USER and SMTP_PASS must be set so notifications are delivered")
        if not self.admin_notify_email:
            problems.append("ADMIN_NOTIFY_EMAIL must be set")
        if problems:
            raise RuntimeError("Production configuration incomplete: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
