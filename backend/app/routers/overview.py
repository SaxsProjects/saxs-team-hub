"""Summaries for the screens: the founder's dashboard, a team member's overview, and the payment list.

Read-only and aggregated in the database, so each screen loads with one request.
"""

import csv
import io
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin, require_member
from ..models import ClientPayment, Invoice, OnboardingItem, Payout, Person, Quotation, Receipt, TaskOrder, User
from ..services import audit, local_tz, today_local
from .me import REQUEST_AGAIN_AFTER
from .people import current_rate

router = APIRouter(prefix="/api", tags=["overview"])

OPEN_INVOICE = ("issued", "part_paid")


class PayoutSummary(BaseModel):
    unpaid_count: int
    unpaid_cents: int
    due_now_count: int
    due_now_cents: int
    due_next_7_days_cents: int
    waiting_for_first_payment_cents: int
    payment_requested_count: int
    paid_this_year_cents: int


class InvoiceSummary(BaseModel):
    outstanding_count: int
    outstanding_cents: int
    overdue_count: int
    overdue_cents: int
    draft_count: int


class DashboardOut(BaseModel):
    today: date
    payouts: PayoutSummary
    invoices: InvoiceSummary
    quotations_awaiting_answer: int
    task_orders_by_status: dict[str, int]
    task_reviews_overdue: int
    people_by_status: dict[str, int]
    received_this_year_cents: int


class MemberOverviewOut(BaseModel):
    today: date
    current_rate_bp: int
    owed_cents: int
    due_now_cents: int
    due_now_count: int
    can_request_payment_count: int
    next_due_on: date | None
    waiting_for_first_payment_cents: int
    paid_this_year_cents: int
    task_orders_to_confirm: int
    task_orders_in_progress: int
    task_orders_awaiting_review: int
    onboarding_open: int


def _year_start_utc(today: date) -> datetime:
    """Midnight on 1 January in South Africa, as UTC, for comparing with stored UTC timestamps."""
    return datetime.combine(date(today.year, 1, 1), time(), tzinfo=local_tz()).astimezone(UTC)


def _sum(db: Session, column, *where) -> int:
    return db.scalar(select(func.coalesce(func.sum(column), 0)).where(*where)) or 0


def _count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _by_status(db: Session, column) -> dict[str, int]:
    return {status: n for status, n in db.execute(select(column, func.count()).group_by(column)).all()}


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    today = today_local()
    unpaid = Payout.paid_at.is_(None)
    year_start = date(today.year, 1, 1)
    open_inv = Invoice.status.in_(OPEN_INVOICE)
    balance = Invoice.total_cents - Invoice.paid_cents - Invoice.credited_cents
    overdue_inv = (open_inv, Invoice.due_date < today)
    return DashboardOut(
        today=today,
        payouts=PayoutSummary(
            unpaid_count=_count(db, Payout, unpaid),
            unpaid_cents=_sum(db, Payout.amount_cents, unpaid),
            due_now_count=_count(db, Payout, unpaid, Payout.due_at <= today),
            due_now_cents=_sum(db, Payout.amount_cents, unpaid, Payout.due_at <= today),
            due_next_7_days_cents=_sum(
                db, Payout.amount_cents, unpaid, Payout.due_at > today, Payout.due_at <= today + timedelta(days=7)
            ),
            waiting_for_first_payment_cents=_sum(db, Payout.amount_cents, unpaid, Payout.due_at.is_(None)),
            payment_requested_count=_count(db, Payout, unpaid, Payout.payment_requested_at.is_not(None)),
            paid_this_year_cents=_sum(db, Payout.amount_cents, Payout.paid_at >= _year_start_utc(today)),
        ),
        invoices=InvoiceSummary(
            outstanding_count=_count(db, Invoice, open_inv),
            outstanding_cents=_sum(db, balance, open_inv),
            overdue_count=_count(db, Invoice, *overdue_inv),
            overdue_cents=_sum(db, balance, *overdue_inv),
            draft_count=_count(db, Invoice, Invoice.status == "draft"),
        ),
        quotations_awaiting_answer=_count(db, Quotation, Quotation.status == "issued"),
        task_orders_by_status=_by_status(db, TaskOrder.status),
        task_reviews_overdue=_count(db, TaskOrder, TaskOrder.status == "submitted", TaskOrder.review_due_on < today),
        people_by_status=_by_status(db, Person.status),
        received_this_year_cents=_sum(db, Receipt.amount_cents, Receipt.received_on >= year_start)
        + _sum(db, ClientPayment.amount_cents, ClientPayment.received_at >= year_start),
    )


@router.get("/me/overview", response_model=MemberOverviewOut)
def my_overview(db: Session = Depends(get_db), user: User = Depends(require_member)):
    today = today_local()
    person: Person = user.person
    mine = Payout.person_id == person.id
    unpaid = (mine, Payout.paid_at.is_(None))
    due_now = (*unpaid, Payout.due_at <= today)
    can_request_before = datetime.now(UTC) - REQUEST_AGAIN_AFTER
    orders = TaskOrder.person_id == person.id
    return MemberOverviewOut(
        today=today,
        current_rate_bp=current_rate(person),
        owed_cents=_sum(db, Payout.amount_cents, *unpaid),
        due_now_cents=_sum(db, Payout.amount_cents, *due_now),
        due_now_count=_count(db, Payout, *due_now),
        can_request_payment_count=_count(
            db,
            Payout,
            *due_now,
            (Payout.payment_requested_at.is_(None)) | (Payout.payment_requested_at < can_request_before),
        ),
        next_due_on=db.scalar(select(func.min(Payout.due_at)).where(*unpaid, Payout.due_at > today)),
        waiting_for_first_payment_cents=_sum(db, Payout.amount_cents, *unpaid, Payout.due_at.is_(None)),
        paid_this_year_cents=_sum(db, Payout.amount_cents, mine, Payout.paid_at >= _year_start_utc(today)),
        task_orders_to_confirm=_count(db, TaskOrder, orders, TaskOrder.status == "proposed"),
        task_orders_in_progress=_count(db, TaskOrder, orders, TaskOrder.status == "confirmed"),
        task_orders_awaiting_review=_count(db, TaskOrder, orders, TaskOrder.status == "submitted"),
        onboarding_open=_count(db, OnboardingItem, OnboardingItem.person_id == person.id, OnboardingItem.done.is_(False)),
    )


def _cell(value: object) -> str:
    """Neutralise spreadsheet formulas (CSV injection): a cell starting with = + - @ is shown as text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/payment-list.csv")
def payment_list(requested_only: bool = False, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Unpaid payouts that are due, as a list to pay from in the banking app.

    No bank account numbers: beneficiaries are saved in the bank, which is where they belong. Pay in the
    bank, then mark each payout as paid with its EFT reference.
    """
    today = today_local()
    q = (
        select(Payout)
        .join(Person, Payout.person_id == Person.id)
        .where(Payout.paid_at.is_(None), Payout.due_at <= today)
        .order_by(Person.full_name, Payout.due_at, Payout.id)
    )
    if requested_only:
        q = q.where(Payout.payment_requested_at.is_not(None))
    payouts = db.scalars(q).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Beneficiary", "Amount (ZAR)", "Reference", "Due date", "Payment requested", "Kind"])
    for p in payouts:
        requested = p.payment_requested_at.astimezone(local_tz()).date().isoformat() if p.payment_requested_at else ""
        writer.writerow(
            [
                _cell(p.person.full_name),
                f"{p.amount_cents // 100}.{p.amount_cents % 100:02d}",
                _cell(p.statement_number),
                p.due_at.isoformat(),
                requested,
                p.kind,
            ]
        )
    total = sum(p.amount_cents for p in payouts)
    audit(db, admin.email, "payout.export_payment_list", "payout", None, after={"count": len(payouts), "total_cents": total})
    db.commit()
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="payment-list-{today.isoformat()}.csv"',
            "Cache-Control": "no-store",
        },
    )
