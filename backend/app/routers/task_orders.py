"""Task Orders for task-fee contractors (agreements SP/ICA/2026/003-005, Schedule B).

Lifecycle:  proposed -> confirmed -> submitted -> accepted
                     \\-> declined   (the contractor may decline a proposed task)
            proposed / confirmed -> cancelled (by the founder, before anything is submitted)
            submitted -> confirmed (the founder explains what remains to be done)

A Task Order is binding once the contractor confirms it. Accepting a submitted task creates the
fee payout: due 7 days after acceptance, or for deferred terms, 30 days after the First Client
Payment when the task was accepted before it. The founder reviews a submission within 5 days;
late reviews are flagged as `review_overdue`.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin, require_member
from ..models import Payout, TaskOrder, User
from ..notifications import notify_admins, notify_person
from ..numbering import allocate_number
from ..payouts import format_zar
from ..schemas import (
    TaskOrderAccept,
    TaskOrderAcceptedOut,
    TaskOrderIn,
    TaskOrderNote,
    TaskOrderOptionalNote,
    TaskOrderOut,
    TaskOrderUpdate,
)
from ..services import audit, today_local
from ..terms import first_client_payment_date, review_due_date, task_fee_due_date
from .people import get_person
from .projects import ELIGIBLE_STAGES, next_statement_number

router = APIRouter(prefix="/api", tags=["task orders"])


def task_order_out(order: TaskOrder) -> TaskOrderOut:
    out = TaskOrderOut.model_validate(order)
    out.review_overdue = order.status == "submitted" and order.review_due_on is not None and order.review_due_on < today_local()
    return out


def locked(db: Session, order_id: int) -> TaskOrder | None:
    """Load a Task Order and lock its row until commit, so two requests cannot change it at once."""
    stmt = select(TaskOrder).where(TaskOrder.id == order_id).with_for_update().execution_options(populate_existing=True)
    return db.scalars(stmt).first()


def get_order(db: Session, order_id: int) -> TaskOrder:
    order = locked(db, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task Order not found")
    return order


def require_status(order: TaskOrder, *allowed: str) -> None:
    if order.status not in allowed:
        needed = " or ".join(allowed)
        raise HTTPException(status.HTTP_409_CONFLICT, f"This Task Order is {order.status}; that needs it to be {needed}")


# ---- Founder -------------------------------------------------------------------------------------


@router.post("/task-orders", response_model=TaskOrderOut, status_code=201)
def create_task_order(body: TaskOrderIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    person = get_person(db, body.person_id)
    if person.status not in ELIGIBLE_STAGES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Task Orders can only be issued to people who accepted an offer")
    if body.due_on < today_local():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The due date cannot be in the past")
    order = TaskOrder(
        number=allocate_number(db, "TO"),
        person_id=person.id,
        title=body.title.strip(),
        deliverable=body.deliverable.strip(),
        fee_cents=body.fee_cents,
        due_on=body.due_on,
        fee_terms=person.fee_terms,
        status="proposed",
    )
    db.add(order)
    db.flush()
    audit(
        db,
        admin.email,
        "task_order.create",
        "task_order",
        order.id,
        after={"number": order.number, "person_id": person.id, "fee_cents": order.fee_cents, "fee_terms": order.fee_terms},
    )
    notify_person(
        db,
        person,
        "task_orders",
        f"New task offered: {order.number}",
        f"{order.title} for {format_zar(order.fee_cents)}, due {order.due_on:%d %b %Y}. Confirm or decline it.",
        "/my/task-orders",
    )
    db.commit()
    return task_order_out(order)


@router.get("/task-orders", response_model=list[TaskOrderOut])
def list_task_orders(
    status_filter: str | None = None,
    person_id: int | None = None,
    review_overdue: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(TaskOrder).order_by(TaskOrder.id.desc())
    if status_filter:
        q = q.where(TaskOrder.status == status_filter)
    if person_id is not None:
        q = q.where(TaskOrder.person_id == person_id)
    if review_overdue:
        q = q.where(TaskOrder.status == "submitted", TaskOrder.review_due_on < today_local())
    return [task_order_out(o) for o in db.scalars(q)]


@router.get("/task-orders/{order_id}", response_model=TaskOrderOut)
def read_task_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return task_order_out(get_order(db, order_id))


@router.patch("/task-orders/{order_id}", response_model=TaskOrderOut)
def update_task_order(order_id: int, body: TaskOrderUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Change a Task Order before the contractor confirms it. After that it is binding and cannot be edited."""
    order = get_order(db, order_id)
    require_status(order, "proposed")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("due_on") and changes["due_on"] < today_local():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The due date cannot be in the past")
    before = {k: getattr(order, k) for k in changes}
    for key, value in changes.items():
        setattr(order, key, value.strip() if isinstance(value, str) else value)
    audit(
        db,
        admin.email,
        "task_order.update",
        "task_order",
        order.id,
        {k: str(v) for k, v in before.items()},
        {k: str(v) for k, v in changes.items()},
    )
    db.commit()
    return task_order_out(order)


@router.post("/task-orders/{order_id}/cancel", response_model=TaskOrderOut)
def cancel_task_order(order_id: int, body: TaskOrderNote, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Withdraw a task before work is submitted. Pay for any work already done is agreed separately in writing."""
    order = get_order(db, order_id)
    require_status(order, "proposed", "confirmed")
    order.status = "cancelled"
    order.closed_reason = body.note.strip()
    audit(db, admin.email, "task_order.cancel", "task_order", order.id, after={"reason": order.closed_reason})
    notify_person(db, order.person, "task_orders", f"Task cancelled: {order.number}", order.closed_reason, "/my/task-orders")
    db.commit()
    return task_order_out(order)


@router.post("/task-orders/{order_id}/request-changes", response_model=TaskOrderOut)
def request_changes(order_id: int, body: TaskOrderNote, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Explain what remains to be done; the task goes back to the contractor."""
    order = get_order(db, order_id)
    require_status(order, "submitted")
    order.status = "confirmed"
    order.review_note = body.note.strip()
    order.review_due_on = None
    audit(db, admin.email, "task_order.request_changes", "task_order", order.id, after={"note": order.review_note})
    notify_person(db, order.person, "task_orders", f"Changes requested: {order.number}", order.review_note, "/my/task-orders")
    db.commit()
    return task_order_out(order)


@router.post("/task-orders/{order_id}/accept", response_model=TaskOrderAcceptedOut)
def accept_task_order(order_id: int, body: TaskOrderAccept, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Confirm the task is complete. This records the fee as a payout."""
    order = get_order(db, order_id)
    require_status(order, "submitted")
    accepted_on = body.accepted_on or today_local()
    if accepted_on > today_local():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The acceptance date cannot be in the future")
    if order.submitted_at and accepted_on < order.submitted_at.date():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The acceptance date cannot be before the task was submitted")
    order.status = "accepted"
    order.accepted_on = accepted_on
    order.review_note = body.note.strip() if body.note else order.review_note
    payout = Payout(
        kind="task_fee",
        person_id=order.person_id,
        task_order_id=order.id,
        amount_cents=order.fee_cents,
        due_at=task_fee_due_date(order.fee_terms, accepted_on, first_client_payment_date(db)),
        statement_number=next_statement_number(db),
        calculation={
            "kind": "task_fee",
            "task_order": order.number,
            "fee_cents": order.fee_cents,
            "fee_terms": order.fee_terms,
            "accepted_on": accepted_on.isoformat(),
        },
    )
    db.add(payout)
    db.flush()
    audit(db, admin.email, "task_order.accept", "task_order", order.id, after={"accepted_on": str(accepted_on)})
    audit(
        db,
        admin.email,
        "payout.create",
        "payout",
        payout.id,
        after={"person_id": order.person_id, "amount_cents": payout.amount_cents, "due_at": str(payout.due_at)},
    )
    notify_person(
        db,
        order.person,
        "task_orders",
        f"Task accepted: {order.number}",
        f"Your fee of {format_zar(payout.amount_cents)} is on statement {payout.statement_number}"
        + (f", due {payout.due_at:%d %b %Y}." if payout.due_at else "."),
        "/my/payouts",
    )
    db.commit()
    return TaskOrderAcceptedOut(task_order=task_order_out(order), payout=payout)


# ---- Contractor ----------------------------------------------------------------------------------


def my_order(db: Session, user: User, order_id: int) -> TaskOrder:
    order = locked(db, order_id)
    if not order or order.person_id != user.person_id:  # don't reveal other people's orders
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task Order not found")
    return order


@router.get("/me/task-orders", response_model=list[TaskOrderOut])
def my_task_orders(db: Session = Depends(get_db), user: User = Depends(require_member)):
    q = select(TaskOrder).where(TaskOrder.person_id == user.person_id).order_by(TaskOrder.id.desc())
    return [task_order_out(o) for o in db.scalars(q)]


@router.post("/me/task-orders/{order_id}/confirm", response_model=TaskOrderOut)
def confirm_task_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_member)):
    """Agree to do the task for the recorded fee. From now on the Task Order is binding on both sides."""
    order = my_order(db, user, order_id)
    require_status(order, "proposed")
    order.status = "confirmed"
    order.confirmed_at = datetime.now(UTC)
    audit(db, user.email, "task_order.confirm", "task_order", order.id, after={"fee_cents": order.fee_cents})
    notify_admins(
        db, "task_orders", f"Task confirmed: {order.number}", f"{order.title} was confirmed and can start.", "/task-orders"
    )
    db.commit()
    return task_order_out(order)


@router.post("/me/task-orders/{order_id}/decline", response_model=TaskOrderOut)
def decline_task_order(
    order_id: int, body: TaskOrderOptionalNote, db: Session = Depends(get_db), user: User = Depends(require_member)
):
    """Turn down a proposed task. There is no consequence for declining."""
    order = my_order(db, user, order_id)
    require_status(order, "proposed")
    order.status = "declined"
    order.closed_reason = body.note.strip() if body.note else None
    audit(db, user.email, "task_order.decline", "task_order", order.id)
    notify_admins(db, "task_orders", f"Task declined: {order.number}", order.title, "/task-orders")
    db.commit()
    return task_order_out(order)


@router.post("/me/task-orders/{order_id}/submit", response_model=TaskOrderOut)
def submit_task_order(order_id: int, body: TaskOrderNote, db: Session = Depends(get_db), user: User = Depends(require_member)):
    """Hand in the deliverable (say where it is). The founder reviews it within 5 days."""
    order = my_order(db, user, order_id)
    require_status(order, "confirmed")
    order.status = "submitted"
    order.submitted_at = datetime.now(UTC)
    order.submission_note = body.note.strip()
    order.review_due_on = review_due_date()
    audit(db, user.email, "task_order.submit", "task_order", order.id, after={"review_due_on": str(order.review_due_on)})
    notify_admins(
        db,
        "reviews",
        f"Task submitted for review: {order.number}",
        f"{order.title}. Accept it or say what remains by {order.review_due_on:%d %b %Y}.",
        "/task-orders",
    )
    db.commit()
    return task_order_out(order)
