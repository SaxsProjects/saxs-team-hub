"""Contractor agreement terms that depend on dates: revenue-share rates and task-fee due dates."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import INITIAL_RATE_BP, ClientPayment, Payout, RatePeriod, Receipt, TaskOrder
from .services import audit, today_local

TASK_FEE_DUE_DAYS = 7  # clause 5: payable within 7 days of acceptance
DEFERRED_FEE_DUE_DAYS = 30  # deferred terms: within 30 days after the First Client Payment
REVIEW_DAYS = 5  # the Company confirms acceptance within 5 days of submission


def rate_at(db: Session, person_id: int, on: date) -> int:
    """The revenue-share rate in force for `person_id` on `on` (the initial rate if no review applies yet)."""
    rate = db.scalar(
        select(RatePeriod.rate_bp)
        .where(RatePeriod.person_id == person_id, RatePeriod.effective_from <= on)
        .order_by(RatePeriod.effective_from.desc())
        .limit(1)
    )
    return rate if rate is not None else INITIAL_RATE_BP


def first_client_payment_date(db: Session) -> date | None:
    """The date the Company first received money from any client (project payments or invoice receipts)."""
    dates = [
        db.scalar(select(func.min(ClientPayment.received_at))),
        db.scalar(select(func.min(Receipt.received_on))),
    ]
    dates = [d for d in dates if d is not None]
    return min(dates) if dates else None


def task_fee_due_date(fee_terms: str, accepted_on: date, first_payment: date | None) -> date | None:
    """When an accepted task's fee is due, or None while a deferred fee waits for the First Client Payment.

    A task accepted on the same day as the First Client Payment counts as accepted after it (7 days),
    the reading that pays the contractor sooner.
    """
    if fee_terms == "deferred" and (first_payment is None or accepted_on < first_payment):
        return first_payment + timedelta(days=DEFERRED_FEE_DUE_DAYS) if first_payment else None
    return accepted_on + timedelta(days=TASK_FEE_DUE_DAYS)


def release_deferred_fees(db: Session, actor: str) -> list[Payout]:
    """Set the due date of unpaid deferred task fees from the First Client Payment. Safe to call repeatedly.

    Recomputed each time, so a payment recorded late with an earlier date moves the due dates too.
    """
    first_payment = first_client_payment_date(db)
    if first_payment is None:
        return []
    unpaid = db.scalars(
        select(Payout)
        .join(TaskOrder, Payout.task_order_id == TaskOrder.id)
        .where(Payout.kind == "task_fee", Payout.paid_at.is_(None), TaskOrder.fee_terms == "deferred")
    ).all()
    changed = []
    for payout in unpaid:
        due = task_fee_due_date(payout.task_order.fee_terms, payout.task_order.accepted_on, first_payment)
        if due != payout.due_at:
            before = {"due_at": str(payout.due_at)}
            payout.due_at = due
            audit(db, actor, "payout.release_deferred", "payout", payout.id, before, {"due_at": str(due)})
            changed.append(payout)
    if changed:
        db.flush()
    return changed


def review_due_date(submitted_on: date | None = None) -> date:
    return (submitted_on or today_local()) + timedelta(days=REVIEW_DAYS)
