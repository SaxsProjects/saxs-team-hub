"""Shared business helpers: audit log, time, documents, onboarding, pipeline stages."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import ActionToken, AuditLog, Document, OnboardingItem, Person, User
from .security import hash_token, new_token, sha256_bytes


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def today_local() -> date:
    return datetime.now(local_tz()).date()


def end_of_day_utc(day: date) -> datetime:
    """23:59:59 on `day` in South African time, as UTC."""
    return datetime.combine(day, time(23, 59, 59), tzinfo=local_tz()).astimezone(UTC)


def audit(
    db: Session,
    actor: str,
    action: str,
    entity: str,
    entity_id: int | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Append an audit entry. Keep personal details (names, emails, bank data) out of before/after."""
    db.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id, before=before, after=after))


def store_document(
    db: Session, *, person_id: int | None, kind: str, filename: str, content_type: str, content: bytes
) -> Document:
    version = (
        db.scalar(select(func.max(Document.version)).where(Document.person_id == person_id, Document.kind == kind)) or 0
    ) + 1
    digest = sha256_bytes(content)
    doc = Document(
        person_id=person_id,
        kind=kind,
        filename=filename[:255],
        content_type=content_type,
        content=content,
        size=len(content),
        sha256=digest,
        version=version,
        storage_key=f"db:{kind}/{person_id or 'none'}/v{version}/{digest[:12]}",
    )
    db.add(doc)
    db.flush()
    return doc


# README §4.4. member_can_complete: the team member may tick it themselves.
DEFAULT_ONBOARDING = [
    ("agreement_signed", "Contractor agreement signed", False),
    ("github_invited", "GitHub account invited to the SaxsProjects organisation (least-privilege access)", False),
    ("two_factor", "Two-factor authentication confirmed", False),
    ("channel_joined", "Team communication channel joined", True),
    ("banking_captured", "Banking details captured (stored encrypted)", False),
    ("standards_read", "Coding standards and security rules read", True),
    ("first_task", "First task assigned", False),
]


def ensure_onboarding(db: Session, person: Person) -> None:
    existing = {i.key for i in person.onboarding_items}
    for position, (key, label, member_can) in enumerate(DEFAULT_ONBOARDING, start=1):
        if key not in existing:
            db.add(OnboardingItem(person_id=person.id, key=key, item=label, position=position, member_can_complete=member_can))


def complete_onboarding_item(db: Session, person: Person, key: str) -> None:
    for item in person.onboarding_items:
        if item.key == key and not item.done:
            item.done = True
            item.done_at = datetime.now(UTC)


# Manual pipeline moves the admin may make after an offer is accepted.
MANUAL_STAGE_MOVES = {"accepted": "agreement_signed", "agreement_signed": "onboarded"}


def set_stage(db: Session, person: Person, stage: str, actor: str) -> None:
    if person.status == stage:
        return
    before = person.status
    person.status = stage
    audit(db, actor, "person.stage", "person", person.id, {"stage": before}, {"stage": stage})


def payout_due_date(received: date) -> date:
    return received + timedelta(days=get_settings().payout_delay_days)


def revoke_sessions(user: User) -> None:
    """Sign the user out everywhere: tokens issued before now stop working."""
    user.sessions_valid_after = datetime.now(UTC)


def issue_action_token(db: Session, user: User, purpose: str, valid_for: timedelta) -> str:
    """Create a one-time link token (only its hash is stored) and invalidate older ones for the same purpose."""
    now = datetime.now(UTC)
    for old in db.scalars(
        select(ActionToken).where(ActionToken.user_id == user.id, ActionToken.purpose == purpose, ActionToken.used_at.is_(None))
    ):
        old.used_at = now
    token = new_token()
    db.add(ActionToken(user_id=user.id, purpose=purpose, token_hash=hash_token(token), expires_at=now + valid_for))
    return token


def link(path: str) -> str:
    return f"{get_settings().frontend_url.rstrip('/')}{path}"
