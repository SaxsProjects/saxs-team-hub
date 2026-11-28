"""Daily housekeeping: expire overdue offers, remind about due payouts, apply POPIA retention.

Run once a day, either with `python -m app.cli daily-jobs` (e.g. a Render cron job) or by calling
POST /api/jobs/daily with the X-Jobs-Token header (e.g. from a scheduled GitHub Action).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .emailer import notify_admin
from .models import Invoice, Offer, Payout, Person, ProjectContributor, Quotation, TaskOrder, User
from .notifications import purge_old
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
            f"for {p.project.name if p.project else 'Task Order ' + p.task_order.number}, due {p.due_at:%d %b %Y}"
            for p in due
        ]
        notify_admin(
            f"{len(due)} contractor payout(s) due",
            "These payouts are due or overdue:\n\n"
            + "\n".join(lines)
            + "\n\nMark each as paid in the Team Hub with its EFT reference.",
            kind="payouts",
            db=db,
            link="/payouts",
        )
    return len(due)


def remind_overdue_reviews(db: Session) -> int:
    """Submitted tasks the founder has not reviewed within the 5 days the agreement promises."""
    late = db.scalars(
        select(TaskOrder)
        .where(TaskOrder.status == "submitted", TaskOrder.review_due_on < today_local())
        .order_by(TaskOrder.review_due_on)
    ).all()
    if late:
        lines = [f"- {o.number}: {o.title} ({o.person.full_name}), review was due {o.review_due_on:%d %b %Y}" for o in late]
        notify_admin(
            f"{len(late)} task review(s) overdue",
            "These submitted tasks are waiting for you to accept them or explain what remains:\n\n" + "\n".join(lines),
            kind="reviews",
            db=db,
            link="/task-orders",
        )
    return len(late)


def apply_retention(db: Session) -> int:
    """Delete candidates who declined (or let the offer expire) longer ago than the retention period."""
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().declined_retention_days)
    purged = 0
    for person in db.scalars(select(Person).where(Person.status.in_(("declined", "expired")), Person.updated_at < cutoff)):
        keep = db.scalar(select(ProjectContributor.id).where(ProjectContributor.person_id == person.id).limit(1))
        keep = keep or db.scalar(select(TaskOrder.id).where(TaskOrder.person_id == person.id).limit(1))
        if keep:  # project and task records must be kept for tax purposes
            continue
        for user in db.scalars(select(User).where(User.person_id == person.id)):
            db.delete(user)
        person_id = person.id
        db.delete(person)
        audit(db, "daily-job", "retention.purge", "person", person_id)
        purged += 1
    db.commit()
    return purged


def expire_quotations(db: Session) -> int:
    """Issued quotations past their validity date become expired."""
    count = 0
    for q in db.scalars(select(Quotation).where(Quotation.status == "issued", Quotation.valid_until < today_local())):
        q.status = "expired"
        audit(db, "daily-job", "quotation.expire", "quotation", q.id)
        count += 1
    db.commit()
    return count


def remind_overdue_invoices(db: Session) -> int:
    overdue = [
        inv
        for inv in db.scalars(
            select(Invoice)
            .where(Invoice.status.in_(("issued", "part_paid")), Invoice.due_date < today_local())
            .order_by(Invoice.due_date)
        )
        if inv.balance_cents > 0
    ]
    if overdue:
        lines = [
            f"- {inv.number}: {inv.client.name}, {format_zar(inv.balance_cents)} due {inv.due_date:%d %b %Y}" for inv in overdue
        ]
        notify_admin(
            f"{len(overdue)} invoice(s) overdue",
            "These invoices are past their due date:\n\n" + "\n".join(lines) + "\n\nFollow up with the client.",
            kind="invoices",
            db=db,
        )
    return len(overdue)


def run_daily(db: Session) -> dict:
    result = {
        "offers_expired": expire_overdue_offers(db),
        "quotations_expired": expire_quotations(db),
        "invoices_overdue": remind_overdue_invoices(db),
        "payouts_due": remind_due_payouts(db),
        "task_reviews_overdue": remind_overdue_reviews(db),
        "people_purged": apply_retention(db),
        "notifications_purged": purge_old(db),
    }
    db.commit()  # the bell entries created by the reminders above
    return result
