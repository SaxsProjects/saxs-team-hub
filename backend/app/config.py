"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field("development", description="development | test | production")

    database_url: str = "sqlite:///./teamhub.db"
    # Optional separate login for migrations (owns the tables). The app itself then runs as a
    # login that can only read and write rows, so it can never alter or drop tables.
    migration_database_url: str = ""

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

    # Outgoing email. Resend (HTTPS API) is used when RESEND_API_KEY is set; hosts such as Render's free
    # plan block outgoing SMTP ports, but not HTTPS. Otherwise SMTP (Zoho Mail: smtppro.zoho.com /
    # smtp.zoho.com, port 465, app-specific password).
    resend_api_key: str = ""
    resend_api_url: str = "https://api.resend.com/emails"
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "SaxsProjects"

    company_name: str = "SaxsProjects"
    timezone: str = "Africa/Johannesburg"

    # Company details printed on quotations, invoices, receipts, credit notes and statements.
    company_legal_name: str = "SaxsProjects (Pty) Ltd"
    company_registration_number: str = ""  # invoices cannot be issued until this is set
    company_vat_number: str = ""  # once set, invoices become TAX INVOICES and VAT is added
    company_address: str = ""  # lines separated by "|"
    company_email: str = ""
    company_phone: str = ""
    company_website: str = ""
    # Banking details printed on invoices. Environment variables only: never commit them.
    company_bank_name: str = ""
    company_bank_account_name: str = ""
    company_bank_account_number: str = ""
    company_bank_branch_code: str = ""
    company_bank_account_type: str = ""

    vat_rate_bp: int = 1500  # 15% South African VAT, used only when company_vat_number is set
    quote_valid_days: int = 30
    invoice_due_days: int = 7
    deposit_percent: int = 50

    # The director's signature, printed on documents the company signs (issued quotations,
    # receipts, credit notes, payout statements and offer acceptance records). PNG or JPEG.
    # Never commit it: on Render use a Secret File (e.g. /etc/secrets/signature.png).
    signature_image_path: str = ""
    signature_image_base64: str = ""
    signatory_name: str = ""
    signatory_title: str = "Director"

    payout_delay_days: int = 7
    declined_retention_days: int = 365
    max_upload_mb: int = 10

    # Behind Render/most proxies the client IP is in X-Forwarded-For. Each proxy appends the address it
    # received the request from, so only the right-most `trusted_proxy_hops` entries can be trusted;
    # anything to the left of them was written by the client and can be faked.
    trust_proxy: bool = True
    trusted_proxy_hops: int = Field(1, ge=0, le=5)

    # Per-account limits, so faking IP addresses cannot get around them.
    # Failed sign-ins from one IP for one account before that IP is locked out of it.
    login_failures_per_account_ip: int = 10
    # Failed sign-ins for one account from all IPs together. Beyond this, only an account with
    # two-factor can still sign in (correct password AND code), so attackers cannot lock the owner out.
    login_failures_per_account: int = 50
    login_lockout_minutes: int = 15
    # Wrong two-factor codes for one account from all IPs together. Past this every sign-in is refused
    # until the lock expires: someone has the password, and the owner is emailed to change it.
    totp_failures_per_account: int = 10
    reset_emails_per_account_per_hour: int = 3

    @field_validator("database_url", "migration_database_url")
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

    @property
    def resend_configured(self) -> bool:
        return bool(self.resend_api_key.strip())

    @property
    def email_sender(self) -> str:
        return (self.smtp_from or self.smtp_user).strip()

    @property
    def email_configured(self) -> bool:
        if self.resend_configured:
            return "@" in self.email_sender
        return self.smtp_configured

    @property
    def vat_registered(self) -> bool:
        return bool(self.company_vat_number.strip())

    @property
    def bank_configured(self) -> bool:
        return bool(
            self.company_bank_name.strip() and self.company_bank_account_number.strip() and self.company_bank_branch_code.strip()
        )

    @property
    def signature_configured(self) -> bool:
        return bool(self.signature_image_path.strip() or self.signature_image_base64.strip())

    @property
    def company_address_lines(self) -> list[str]:
        return [line.strip() for line in self.company_address.split("|") if line.strip()]

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
        for name, url in (("DATABASE_URL", self.database_url), ("MIGRATION_DATABASE_URL", self.migration_database_url)):
            if (
                url
                and not url.startswith("sqlite")
                and not any(f"sslmode={mode}" in url for mode in ("require", "verify-ca", "verify-full"))
            ):
                problems.append(f"{name} must use an encrypted connection (sslmode=require or stricter)")
        if not self.email_configured:
            problems.append(
                "Email must be configured so notifications are delivered: RESEND_API_KEY with SMTP_FROM, "
                "or SMTP_HOST, SMTP_USER and SMTP_PASS"
            )
        if not self.admin_notify_email:
            problems.append("ADMIN_NOTIFY_EMAIL must be set")
        if not self.signature_configured or not self.signatory_name.strip():
            problems.append(
                "SIGNATURE_IMAGE_PATH (or SIGNATURE_IMAGE_BASE64) and SIGNATORY_NAME must be set "
                "so signed documents carry the signature"
            )
        if problems:
            raise RuntimeError("Production configuration incomplete: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
