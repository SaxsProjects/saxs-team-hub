"""In-app notifications (the bell). Every user sees only their own; the bell shows how many are unread.

`notify` adds rows to the caller's session, so they are saved (or rolled back) with the change that caused
them; the caller commits. `notify_detached` uses its own session for code that runs after the request
has finished (background tasks).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Notification, User

TITLE_MAX = 200
BODY_MAX = 4000
KEEP_READ_FOR = timedelta(days=180)


def _clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def notify(db: Session, user_ids: list[int], kind: str, title: str, body: str | None = None, link: str | None = None) -> int:
    title = _clip(title, TITLE_MAX) or ""
    added = 0
    for user_id in dict.fromkeys(user_ids):  # once per user, in order
        unread_same = db.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id, Notification.title == title, Notification.read_at.is_(None)
            )
        )
        if unread_same:  # the same reminder is still unread: refresh it instead of stacking copies
            existing = db.get(Notification, unread_same)
            existing.body = _clip(body, BODY_MAX)
            existing.created_at = datetime.now(UTC)
            continue
        db.add(Notification(user_id=user_id, kind=kind[:32], title=title, body=_clip(body, BODY_MAX), link=link))
        added += 1
    return added


def admin_ids(db: Session) -> list[int]:
    return list(db.scalars(select(User.id).where(User.role == "admin", User.is_active.is_(True)).order_by(User.id)))


def notify_person(db: Session, person, kind: str, title: str, body: str | None = None, link: str | None = None) -> int:
    """Notify the team member account linked to `person` (if they have one yet)."""
    if person is None:
        return 0
    ids = list(db.scalars(select(User.id).where(User.person_id == person.id, User.is_active.is_(True))))
    return notify(db, ids, kind, title, body, link)


def notify_admins(db: Session, kind: str, title: str, body: str | None = None, link: str | None = None) -> int:
    return notify(db, admin_ids(db), kind, title, body, link)


def notify_detached(
    kind: str, title: str, body: str | None = None, link: str | None = None, user_ids: list[int] | None = None
) -> None:
    """For background tasks: saves in its own transaction. `user_ids=None` means every admin."""
    with SessionLocal() as db:
        notify(db, admin_ids(db) if user_ids is None else user_ids, kind, title, body, link)
        db.commit()


def unread_count(db: Session, user_id: int) -> int:
    stmt = select(func.count(Notification.id)).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    return int(db.scalar(stmt) or 0)


def mark_read(db: Session, user_id: int, ids: list[int] | None = None) -> int:
    stmt = update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    return db.execute(stmt.values(read_at=datetime.now(UTC))).rowcount or 0


def purge_old(db: Session) -> int:
    """Read notifications older than 180 days are deleted (they only point at records kept elsewhere)."""
    cutoff = datetime.now(UTC) - KEEP_READ_FOR
    stmt = delete(Notification).where(Notification.read_at.is_not(None), Notification.created_at < cutoff)
    return db.execute(stmt).rowcount or 0
