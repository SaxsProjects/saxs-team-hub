"""Database tables. Money is always integer cents (ZAR); rates and shares are basis points (1% = 100)."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, utcnow

# Pipeline stages for a person (README §4.2).
STAGES = ("draft", "sent", "viewed", "accepted", "declined", "expired", "agreement_signed", "onboarded")
OFFER_STATUSES = ("draft", "sent", "viewed", "accepted", "declined", "expired", "revoked")
PROJECT_STATUSES = ("planned", "in_progress", "completed", "cancelled")
DOCUMENT_KINDS = (
    "offer_pdf",
    "acceptance",
    "agreement",
    "other",
    "quotation",
    "invoice",
    "receipt",
    "credit_note",
    "company_template",
)
# The company template library (Settings > Templates).
TEMPLATE_CATEGORIES = ("letterhead", "offer", "contract", "policy", "finance", "other")
ROLES = ("admin", "member")
QUOTATION_STATUSES = ("draft", "issued", "accepted", "declined", "expired")
INVOICE_STATUSES = ("draft", "issued", "part_paid", "paid", "void")
PAYMENT_METHODS = ("eft", "cash", "card", "other")
TASK_ORDER_STATUSES = ("proposed", "confirmed", "submitted", "accepted", "declined", "cancelled")
PAYOUT_KINDS = ("revenue_share", "task_fee")
# Task-fee agreements: "standard" pays 7 days after acceptance; "deferred" (SP/ICA/2026/004 and 005) holds
# fees for tasks accepted before the First Client Payment until 30 days after that payment.
FEE_TERMS = ("standard", "deferred")

# Contractor agreement: 15% initial rate, 20% after a written review.
INITIAL_RATE_BP = 1500
REVIEWED_RATE_BP = 2000
ALLOWED_RATES_BP = (INITIAL_RATE_BP, REVIEWED_RATE_BP)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Sessions (JWTs) issued before this moment are rejected: set on password change/reset and deactivation.
    sessions_valid_after: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Profile picture: a cleaned 512x512 WebP (see app/avatars.py). Deferred so it loads only when served.
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Founder emails switched off, e.g. {"invoices": false}. Missing keys mean on (see emailer.NOTIFY_KINDS).
    notify_prefs: Mapped[dict | None] = mapped_column(JSON)

    person: Mapped["Person | None"] = relationship()


class SignInSession(Base):
    """One signed-in browser or device. The renewal cookie holds a random token; only its hash is stored.

    Each renewal replaces the token. The previous hash is kept so a stolen, already-used token is
    recognised: presenting it ends the session.
    """

    __tablename__ = "sign_in_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    renewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_reason: Mapped[str | None] = mapped_column(String(32))
    user_agent: Mapped[str | None] = mapped_column(String(200))


class TrustedDevice(Base):
    """A phone or computer the person chose to trust after a full sign-in (password and two-factor).

    On a trusted device they unlock with a passkey (Face ID, fingerprint, Windows Hello) or their password
    alone. The device cookie holds a random token; only its hash is stored. Trust ends when it is removed,
    after a password reset, or after `device_trust_days` without use.
    """

    __tablename__ = "trusted_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    failed_unlocks: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_reason: Mapped[str | None] = mapped_column(String(32))

    passkeys: Mapped[list["Passkey"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class Passkey(Base):
    """A WebAuthn credential on a trusted device. Only the public key is stored."""

    __tablename__ = "passkeys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("trusted_devices.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    device: Mapped[TrustedDevice] = relationship(back_populates="passkeys")


class WebAuthnChallenge(Base):
    """A one-time passkey challenge, valid for a few minutes."""

    __tablename__ = "webauthn_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("trusted_devices.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # register | unlock
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ActionToken(Base):
    """One-time tokens emailed to people (e.g. set your password). Only the hash is stored."""

    __tablename__ = "action_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    rate_bp: Mapped[int] = mapped_column(Integer, default=INITIAL_RATE_BP)
    rate_review_note: Mapped[str | None] = mapped_column(Text)
    fee_terms: Mapped[str] = mapped_column(String(16), default="standard", server_default="standard")
    # Encrypted at rest (Fernet). Only collected when needed (POPIA).
    sensitive_enc: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    offers: Mapped[list["Offer"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    onboarding_items: Mapped[list["OnboardingItem"]] = relationship(
        back_populates="person", cascade="all, delete-orphan", order_by="OnboardingItem.position"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="person", cascade="all, delete-orphan", foreign_keys="Document.person_id"
    )
    rate_periods: Mapped[list["RatePeriod"]] = relationship(cascade="all, delete-orphan", order_by="RatePeriod.effective_from")
    account: Mapped["User | None"] = relationship(viewonly=True, uselist=False, primaryjoin="User.person_id == Person.id")


class RatePeriod(Base):
    """A person's revenue-share rate from `effective_from` until the next period starts.

    Each client instalment is shared at the rate in force on the date it was received. A person
    with no period on or before a date is on the initial rate.
    """

    __tablename__ = "rate_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    rate_bp: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date)
    review_note: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("person_id", "effective_from"),
        CheckConstraint("rate_bp IN (1500, 2000)", name="ck_rate_period_rate"),
    )


class Document(Base):
    """A stored file. Content lives in the database so signed records survive redeploys."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    storage_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    person: Mapped["Person | None"] = relationship(back_populates="documents", foreign_keys=[person_id])


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(200))
    reference: Mapped[str] = mapped_column(String(64), unique=True)
    deadline: Mapped[date] = mapped_column(Date)
    message: Mapped[str | None] = mapped_column(Text)
    pdf_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    offer_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    viewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expired_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    person: Mapped[Person] = relationship(back_populates="offers")
    pdf_document: Mapped[Document | None] = relationship(foreign_keys=[pdf_document_id])
    response: Mapped["OfferResponse | None"] = relationship(back_populates="offer", cascade="all, delete-orphan")


class OfferResponse(Base):
    __tablename__ = "offer_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), unique=True)
    decision: Mapped[str] = mapped_column(String(16))
    typed_signature: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    offer_hash: Mapped[str] = mapped_column(String(64))
    acceptance_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    responded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    offer: Mapped[Offer] = relationship(back_populates="response")


class OnboardingItem(Base):
    __tablename__ = "onboarding_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    item: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)
    member_can_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    person: Mapped[Person] = relationship(back_populates="onboarding_items")

    __table_args__ = (UniqueConstraint("person_id", "key"),)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    client_name: Mapped[str] = mapped_column(String(200))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    contributors: Mapped[list["ProjectContributor"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    payments: Mapped[list["ClientPayment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ClientPayment.id"
    )
    costs: Mapped[list["ProjectCost"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectContributor(Base):
    __tablename__ = "project_contributors"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"))
    work_share_bp: Mapped[int] = mapped_column(Integer)
    rate_bp: Mapped[int] = mapped_column(Integer)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    project: Mapped[Project] = relationship(back_populates="contributors")
    person: Mapped[Person] = relationship()

    __table_args__ = (UniqueConstraint("project_id", "person_id"),)


class ClientPayment(Base):
    __tablename__ = "client_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[date] = mapped_column(Date)
    reference: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="payments")


class ProjectCost(Base):
    __tablename__ = "project_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    description: Mapped[str] = mapped_column(String(255))
    amount_cents: Mapped[int] = mapped_column(Integer)
    incurred_at: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="costs")


class TaskOrder(Base):
    """A fixed-fee task (Schedule B of the task-fee agreements). Binding once the contractor confirms it."""

    __tablename__ = "task_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    deliverable: Mapped[str] = mapped_column(Text)
    fee_cents: Mapped[int] = mapped_column(Integer)
    due_on: Mapped[date] = mapped_column(Date)
    fee_terms: Mapped[str] = mapped_column(String(16))  # copied from the person when the order is made
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    submission_note: Mapped[str | None] = mapped_column(Text)
    review_due_on: Mapped[date | None] = mapped_column(Date)
    review_note: Mapped[str | None] = mapped_column(Text)
    accepted_on: Mapped[date | None] = mapped_column(Date)
    closed_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    person: Mapped[Person] = relationship()

    __table_args__ = (CheckConstraint("fee_cents > 0", name="ck_task_order_fee"),)


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="revenue_share", server_default="revenue_share")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    client_payment_id: Mapped[int | None] = mapped_column(ForeignKey("client_payments.id", ondelete="RESTRICT"))
    task_order_id: Mapped[int | None] = mapped_column(ForeignKey("task_orders.id", ondelete="RESTRICT"), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    # None while a deferred task fee is waiting for the First Client Payment.
    due_at: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # When the contractor last asked for this payout to be paid (Team Hub "Request payment").
    payment_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    eft_reference: Mapped[str | None] = mapped_column(String(120))
    statement_number: Mapped[str] = mapped_column(String(32), unique=True)
    calculation: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    project: Mapped[Project | None] = relationship()
    person: Mapped[Person] = relationship()
    client_payment: Mapped[ClientPayment | None] = relationship()
    task_order: Mapped[TaskOrder | None] = relationship()

    __table_args__ = (
        UniqueConstraint("client_payment_id", "person_id"),
        CheckConstraint(
            "(kind = 'revenue_share' AND project_id IS NOT NULL AND client_payment_id IS NOT NULL AND task_order_id IS NULL)"
            " OR (kind = 'task_fee' AND task_order_id IS NOT NULL AND project_id IS NULL AND client_payment_id IS NULL)",
            name="ck_payout_source",
        ),
    )


# ---- Finance: clients, quotations, invoices, receipts, credit notes ------------------------------


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    registration_number: Mapped[str | None] = mapped_column(String(64))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class DocumentSequence(Base):
    """Last number used per document type and year. Locked while a number is assigned, so numbers never repeat or skip."""

    __tablename__ = "document_sequences"

    doc_type: Mapped[str] = mapped_column(String(8), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, default=0)


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(32), unique=True)  # assigned only when issued
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    issue_date: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    vat_rate_bp: Mapped[int] = mapped_column(Integer, default=0)
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    vat_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    pdf_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    client: Mapped[Client] = relationship()
    project: Mapped["Project | None"] = relationship()
    lines: Mapped[list["LineItem"]] = relationship(
        cascade="all, delete-orphan", order_by="LineItem.position", foreign_keys="LineItem.quotation_id"
    )

    __table_args__ = (
        CheckConstraint("total_cents >= 0 AND subtotal_cents >= 0 AND vat_cents >= 0", name="ck_quotation_amounts"),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(32), unique=True)  # assigned only when issued
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    quotation_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    vat_rate_bp: Mapped[int] = mapped_column(Integer, default=0)
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    vat_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    paid_cents: Mapped[int] = mapped_column(Integer, default=0)
    credited_cents: Mapped[int] = mapped_column(Integer, default=0)
    pdf_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    client: Mapped[Client] = relationship()
    project: Mapped["Project | None"] = relationship()
    quotation: Mapped[Quotation | None] = relationship()
    lines: Mapped[list["LineItem"]] = relationship(
        cascade="all, delete-orphan", order_by="LineItem.position", foreign_keys="LineItem.invoice_id"
    )
    receipts: Mapped[list["Receipt"]] = relationship(back_populates="invoice", order_by="Receipt.id")
    credit_notes: Mapped[list["CreditNote"]] = relationship(back_populates="invoice", order_by="CreditNote.id")

    __table_args__ = (
        CheckConstraint(
            "total_cents >= 0 AND subtotal_cents >= 0 AND vat_cents >= 0 AND paid_cents >= 0 AND credited_cents >= 0"
            " AND paid_cents + credited_cents <= total_cents",
            name="ck_invoice_amounts",
        ),
    )

    @property
    def balance_cents(self) -> int:
        return self.total_cents - self.paid_cents - self.credited_cents


class LineItem(Base):
    """A line on a quotation or an invoice (exactly one of the two)."""

    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    line_total_cents: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("(quotation_id IS NULL) <> (invoice_id IS NULL)", name="ck_line_item_parent"),
        CheckConstraint("quantity > 0 AND unit_price_cents >= 0 AND line_total_cents >= 0", name="ck_line_item_amounts"),
    )


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    client_payment_id: Mapped[int | None] = mapped_column(ForeignKey("client_payments.id", ondelete="RESTRICT"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    received_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(16))
    reference: Mapped[str] = mapped_column(String(120))
    issue_date: Mapped[date] = mapped_column(Date)
    pdf_document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    invoice: Mapped[Invoice] = relationship(back_populates="receipts")

    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_receipt_amount"),)


class CreditNote(Base):
    """Corrects an issued invoice. Issued documents are never edited or deleted."""

    __tablename__ = "credit_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    amount_cents: Mapped[int] = mapped_column(Integer)
    issue_date: Mapped[date] = mapped_column(Date)
    pdf_document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    invoice: Mapped[Invoice] = relationship(back_populates="credit_notes")

    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_credit_note_amount"),)


class CompanyProfile(Base):
    """Company details edited in the app (one row). Values override the server settings; stored encrypted."""

    __tablename__ = "company_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_enc: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(320))


class AuditLog(Base):
    """Append-only record of every important change. Never updated or deleted by the app."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class CompanyTemplate(Base):
    """An official company template (letterhead, offer letter, contract...). Founder only.

    Uploading a new file adds a version; earlier versions are kept. Templates are archived, never deleted."""

    __tablename__ = "company_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(320))

    versions: Mapped[list["CompanyTemplateVersion"]] = relationship(
        back_populates="template", order_by="desc(CompanyTemplateVersion.version)"
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('letterhead', 'offer', 'contract', 'policy', 'finance', 'other')", name="ck_company_template_category"
        ),
    )


class CompanyTemplateVersion(Base):
    __tablename__ = "company_template_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("company_templates.id", ondelete="RESTRICT"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    note: Mapped[str | None] = mapped_column(String(300))
    uploaded_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    template: Mapped[CompanyTemplate] = relationship(back_populates="versions")
    document: Mapped[Document] = relationship()

    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_company_template_version"),)
