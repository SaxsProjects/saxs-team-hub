"""Database tables. Money is always integer cents (ZAR); rates and shares are basis points (1% = 100)."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
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
DOCUMENT_KINDS = ("offer_pdf", "acceptance", "agreement", "other")
ROLES = ("admin", "member")

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

    person: Mapped["Person | None"] = relationship()


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


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    client_payment_id: Mapped[int] = mapped_column(ForeignKey("client_payments.id", ondelete="RESTRICT"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[date] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    eft_reference: Mapped[str | None] = mapped_column(String(120))
    statement_number: Mapped[str] = mapped_column(String(32), unique=True)
    calculation: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    project: Mapped[Project] = relationship()
    person: Mapped[Person] = relationship()
    client_payment: Mapped[ClientPayment] = relationship()

    __table_args__ = (UniqueConstraint("client_payment_id", "person_id"),)


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
