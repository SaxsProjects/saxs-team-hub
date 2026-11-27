"""Request and response shapes (validated by Pydantic)."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import ALLOWED_RATES_BP, FEE_TERMS


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Auth -------------------------------------------------------------------


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class SetPasswordIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class AccessIn(BaseModel):
    active: bool


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeIn(BaseModel):
    code: str


class NotificationPrefs(BaseModel):
    """Founder emails; each one can be switched off."""

    offers: bool = True
    reviews: bool = True
    payouts: bool = True
    invoices: bool = True


class MeOut(BaseModel):
    id: int
    email: str
    role: str
    person_id: int | None
    totp_enabled: bool
    two_factor_required: bool
    full_name: str | None = None
    avatar_url: str | None = None


# ---- People -------------------------------------------------------------------


class PersonCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)


class PersonUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    rate_bp: int | None = None
    rate_review_note: str | None = Field(default=None, max_length=2000)
    rate_effective_from: date | None = Field(
        default=None, description="Date of the written review the new rate applies from (default: today)"
    )
    fee_terms: str | None = Field(default=None, description="Task-fee terms: standard or deferred")

    @field_validator("fee_terms")
    @classmethod
    def _fee_terms(cls, v):
        if v is not None and v not in FEE_TERMS:
            raise ValueError(f"fee_terms must be one of {FEE_TERMS}")
        return v

    @field_validator("rate_bp")
    @classmethod
    def _rate(cls, v):
        if v is not None and v not in ALLOWED_RATES_BP:
            raise ValueError(f"rate_bp must be one of {ALLOWED_RATES_BP} (15% initial, 20% after written review)")
        return v


class PersonOut(ORM):
    id: int
    full_name: str
    email: str
    phone: str | None
    status: str
    rate_bp: int
    fee_terms: str = "standard"
    created_at: datetime
    has_sensitive_details: bool = False
    avatar_url: str | None = None


class RatePeriodOut(ORM):
    id: int
    person_id: int
    rate_bp: int
    effective_from: date
    review_note: str
    created_by: str
    created_at: datetime


class StageIn(BaseModel):
    stage: str


class SensitiveIn(BaseModel):
    bank_name: str = Field(min_length=2, max_length=100)
    account_holder: str = Field(min_length=2, max_length=200)
    account_number: str = Field(pattern=r"^[0-9 ]{6,20}$")
    branch_code: str = Field(pattern=r"^[0-9]{4,10}$")
    account_type: str = Field(default="cheque", max_length=40)
    id_number: str | None = Field(default=None, pattern=r"^[0-9A-Za-z]{6,20}$")


# ---- Offers -------------------------------------------------------------------


class OfferCreate(BaseModel):
    person_id: int
    role: str = Field(min_length=2, max_length=200)
    deadline: date
    reference: str | None = Field(default=None, max_length=64)
    message: str | None = Field(default=None, max_length=5000)


class OfferUpdate(BaseModel):
    role: str | None = Field(default=None, min_length=2, max_length=200)
    deadline: date | None = None
    message: str | None = Field(default=None, max_length=5000)


class OfferOut(ORM):
    id: int
    person_id: int
    role: str
    reference: str
    deadline: date
    message: str | None
    status: str
    has_pdf: bool
    sent_at: datetime | None
    viewed_at: datetime | None
    responded_at: datetime | None
    token_expires_at: datetime | None
    overdue: bool = False


class OfferSentOut(OfferOut):
    offer_link: str


class PublicOfferOut(BaseModel):
    reference: str
    role: str
    candidate_name: str
    deadline: date
    message: str | None
    status: str
    has_pdf: bool
    company_name: str
    privacy_notice: str
    can_respond: bool


class AcceptIn(BaseModel):
    typed_signature: str = Field(min_length=2, max_length=200)
    agree: bool


class DeclineIn(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


# ---- Onboarding -----------------------------------------------------------------


class OnboardingItemOut(ORM):
    id: int
    key: str
    item: str
    position: int
    member_can_complete: bool
    done: bool
    done_at: datetime | None


class OnboardingUpdate(BaseModel):
    done: bool


# ---- Projects & payouts ---------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    client_name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    client_name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = None


class ContributorIn(BaseModel):
    person_id: int
    work_share_bp: int = Field(gt=0, le=10_000, description="Agreed work share in basis points (50% = 5000)")


class ContributorOut(ORM):
    id: int
    person_id: int
    work_share_bp: int
    rate_bp: int
    locked_at: datetime | None


class PaymentIn(BaseModel):
    amount_cents: int = Field(gt=0)
    received_at: date
    reference: str = Field(min_length=1, max_length=120)


class CostIn(BaseModel):
    description: str = Field(min_length=2, max_length=255)
    amount_cents: int = Field(gt=0)
    incurred_at: date


class PaymentOut(ORM):
    id: int
    amount_cents: int
    received_at: date
    reference: str


class CostOut(ORM):
    id: int
    description: str
    amount_cents: int
    incurred_at: date


class PayoutOut(ORM):
    id: int
    kind: str
    project_id: int | None
    person_id: int
    client_payment_id: int | None
    task_order_id: int | None
    amount_cents: int
    due_at: date | None
    paid_at: datetime | None
    payment_requested_at: datetime | None = None
    eft_reference: str | None
    statement_number: str
    calculation: dict


class ProjectOut(ORM):
    id: int
    name: str
    client_name: str
    description: str | None
    status: str
    created_at: datetime


class ProjectDetailOut(ProjectOut):
    contributors: list[ContributorOut]
    payments: list[PaymentOut]
    costs: list[CostOut]
    received_cents: int
    costs_cents: int
    net_income_cents: int


class PaymentRecordedOut(BaseModel):
    payment: PaymentOut
    payouts: list[PayoutOut]


class MarkPaidIn(BaseModel):
    eft_reference: str = Field(min_length=2, max_length=120)


# ---- Documents & audit ---------------------------------------------------------


class DocumentOut(ORM):
    id: int
    person_id: int | None
    kind: str
    filename: str
    content_type: str
    size: int
    sha256: str
    version: int
    created_at: datetime


class AuditOut(ORM):
    id: int
    actor: str
    action: str
    entity: str
    entity_id: int | None
    before: dict | None
    after: dict | None
    at: datetime


# ---- Task Orders (task-fee contractors) ----------------------------------------------------------


class TaskOrderIn(BaseModel):
    person_id: int
    title: str = Field(min_length=3, max_length=200)
    deliverable: str = Field(min_length=3, max_length=5000)
    # Indicative fees are R150-R500; the cap only catches typing mistakes (R10,000).
    fee_cents: int = Field(gt=0, le=1_000_000)
    due_on: date


class TaskOrderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    deliverable: str | None = Field(default=None, min_length=3, max_length=5000)
    fee_cents: int | None = Field(default=None, gt=0, le=1_000_000)
    due_on: date | None = None


class TaskOrderNote(BaseModel):
    note: str = Field(min_length=3, max_length=5000)


class TaskOrderOptionalNote(BaseModel):
    note: str | None = Field(default=None, max_length=5000)


class TaskOrderAccept(BaseModel):
    note: str | None = Field(default=None, max_length=5000)
    accepted_on: date | None = Field(default=None, description="Default: today. Cannot be in the future.")


class TaskOrderOut(ORM):
    id: int
    number: str
    person_id: int
    title: str
    deliverable: str
    fee_cents: int
    due_on: date
    fee_terms: str
    status: str
    confirmed_at: datetime | None
    submitted_at: datetime | None
    submission_note: str | None
    review_due_on: date | None
    review_note: str | None
    accepted_on: date | None
    closed_reason: str | None
    created_at: datetime
    review_overdue: bool = False


class TaskOrderAcceptedOut(BaseModel):
    task_order: TaskOrderOut
    payout: PayoutOut
