"""Daily housekeeping: expire overdue offers, remind about due payouts, apply POPIA retention.

Run once a day, either with `python -m app.cli daily-jobs` (e.g. a Render cron job) or by calling
POST /api/jobs/daily with the X-Jobs-Token header (e.g. from a scheduled GitHub Action).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .emailer import notify_admin
from .models import Offer, Payout, Person, ProjectContributor, User
from .payouts import format_zar
from .services import audit, today_local


def expire_overdue_offers(db: Session) -> int:
    from .routers.offers import expire_offer

    now = datetime.now(UTC)
    count = 0
    for offer in db.scalars(select(Offer).where(Offer.status.in_(("sent", "viewed")))):
        if offer.token_expires_at and offer.token_expires_at < now:
            expire_offer(db, offer, actor="daily-job")
            count += 1
    db.commit()
    return count


def remind_due_payouts(db: Session) -> int:
    due = db.scalars(select(Payout).where(Payout.paid_at.is_(None), Payout.due_at <= today_local()).order_by(Payout.due_at)).all()
    if due:
        lines = [
            f"- {p.statement_number}: {p.person.full_name}, {format_zar(p.amount_cents)} "
            f"for {p.project.name}, due {p.due_at:%d %b %Y}"
            for p in due
        ]
        notify_admin(
            f"{len(due)} contractor payout(s) due",
            "These payouts are due or overdue:\n\n"
            + "\n".join(lines)
            + "\n\nMark each as paid in the Team Hub with its EFT reference.",
        )
    return len(due)


def apply_retention(db: Session) -> int:
    """Delete candidates who declined (or let the offer expire) longer ago than the retention period."""
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().declined_retention_days)
    purged = 0
    for person in db.scalars(select(Person).where(Person.status.in_(("declined", "expired")), Person.updated_at < cutoff)):
        if db.scalar(select(ProjectContributor.id).where(ProjectContributor.person_id == person.id).limit(1)):
            continue
        for user in db.scalars(select(User).where(User.person_id == person.id)):
            db.delete(user)
        person_id = person.id
        db.delete(person)
        audit(db, "daily-job", "retention.purge", "person", person_id)
        purged += 1
    db.commit()
    return purged


def run_daily(db: Session) -> dict:
    return {
        "offers_expired": expire_overdue_offers(db),
        "payouts_due": remind_due_payouts(db),
        "people_purged": apply_retention(db),
    }
