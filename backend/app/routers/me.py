"""What a signed-in team member can see: only their own data."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require_admin, require_member
from ..emailer import notify_admin
from ..models import AuditLog, Document, OnboardingItem, Payout, ProjectContributor, User
from ..payouts import format_zar
from ..schemas import (
    AuditOut,
    DocumentOut,
    OnboardingItemOut,
    OnboardingUpdate,
    PayoutOut,
    PersonOut,
    RatePeriodOut,
    SensitiveIn,
)
from ..security import decrypt_json
from ..services import audit, today_local
from .people import current_rate, mask, person_out, save_sensitive

router = APIRouter(prefix="/api", tags=["team member"])

MEMBER_VISIBLE_KINDS = ("offer_pdf", "acceptance", "agreement")


@router.get("/me/profile", response_model=PersonOut)
def my_profile(user: User = Depends(require_member)):
    return person_out(user.person)


@router.get("/me/onboarding", response_model=list[OnboardingItemOut])
def my_onboarding(user: User = Depends(require_member)):
    return user.person.onboarding_items


@router.patch("/me/onboarding/{item_id}", response_model=OnboardingItemOut)
def tick_my_item(item_id: int, body: OnboardingUpdate, db: Session = Depends(get_db), user: User = Depends(require_member)):
    item = db.get(OnboardingItem, item_id)
    if not item or item.person_id != user.person_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist item not found")
    if not item.member_can_complete:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The founder confirms this item")
    item.done = body.done
    item.done_at = datetime.now(UTC) if body.done else None
    audit(db, user.email, "onboarding.update", "onboarding_item", item.id, after={"key": item.key, "done": body.done})
    db.commit()
    return item


@router.put("/me/sensitive", status_code=204)
def my_sensitive(body: SensitiveIn, db: Session = Depends(get_db), user: User = Depends(require_member)):
    save_sensitive(db, user.person, body, user.email)
    db.commit()


@router.get("/me/sensitive")
def read_my_sensitive(user: User = Depends(require_member)):
    details = decrypt_json(user.person.sensitive_enc)
    if details is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No details captured yet")
    return mask(details)


@router.get("/me/projects")
def my_projects(db: Session = Depends(get_db), user: User = Depends(require_member)):
    rows = db.scalars(select(ProjectContributor).where(ProjectContributor.person_id == user.person_id))
    return [
        {
            "project_id": c.project_id,
            "project": c.project.name,
            "client": c.project.client_name,
            "status": c.project.status,
            "work_share_bp": c.work_share_bp,
            "rate_bp": c.rate_bp,  # rate when added to the project
            "current_rate_bp": current_rate(user.person),  # each instalment uses the rate on its payment date
            "locked_at": c.locked_at,
        }
        for c in rows
    ]


@router.get("/me/rates", response_model=list[RatePeriodOut])
def my_rates(user: User = Depends(require_member)):
    """My recorded rate changes. Before the first one, the initial 15% applies."""
    return user.person.rate_periods


@router.get("/me/payouts", response_model=list[PayoutOut])
def my_payouts(db: Session = Depends(get_db), user: User = Depends(require_member)):
    return db.scalars(
        select(Payout).where(Payout.person_id == user.person_id).order_by(Payout.due_at.asc().nulls_last(), Payout.id)
    ).all()


REQUEST_AGAIN_AFTER = timedelta(days=3)


@router.post("/me/payouts/{payout_id}/request-payment", response_model=PayoutOut)
def request_payment(payout_id: int, db: Session = Depends(get_db), user: User = Depends(require_member)):
    """Ask the founder to pay a payout that is due. The founder pays by EFT and marks it paid;
    the Team Hub never moves money itself."""
    payout = db.scalars(
        select(Payout).where(Payout.id == payout_id).with_for_update().execution_options(populate_existing=True)
    ).first()
    if not payout or payout.person_id != user.person_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payout not found")
    if payout.paid_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This payout has already been paid")
    if payout.due_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Not payable yet: it becomes due after the first client payment")
    if payout.due_at > today_local():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Not due yet: it is due on {payout.due_at:%d %b %Y}")
    now = datetime.now(UTC)
    if payout.payment_requested_at and now - payout.payment_requested_at < REQUEST_AGAIN_AFTER:
        raise HTTPException(status.HTTP_409_CONFLICT, "Payment was already requested; you can remind again after 3 days")
    reminder = payout.payment_requested_at is not None
    payout.payment_requested_at = now
    audit(db, user.email, "payout.request_payment", "payout", payout.id, after={"reminder": reminder})
    db.commit()
    notify_admin(
        f"Payment {'reminder' if reminder else 'request'}: {payout.statement_number}",
        f"{user.person.full_name} asks to be paid {format_zar(payout.amount_cents)} "
        f"(statement {payout.statement_number}, due {payout.due_at:%d %b %Y}).\n\n"
        "Pay it by EFT from the business account, then mark it as paid in the Team Hub with the EFT reference.",
        kind="payouts",
        db=db,
    )
    return payout


@router.get("/me/documents", response_model=list[DocumentOut])
def my_documents(db: Session = Depends(get_db), user: User = Depends(require_member)):
    return db.scalars(select(Document).where(Document.person_id == user.person_id, Document.kind.in_(MEMBER_VISIBLE_KINDS))).all()


@router.get("/documents/{document_id}")
def download_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = db.get(Document, document_id)
    if user.role == "admin":
        require_admin(user)
        allowed = doc is not None
    else:
        allowed = doc is not None and doc.person_id == user.person_id and doc.kind in MEMBER_VISIBLE_KINDS
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return Response(
        doc.content,
        media_type=doc.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{doc.filename}"',
            "X-Content-SHA256": doc.sha256,
        },
    )


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    entity: str | None = None,
    entity_id: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 1000))
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id is not None:
        q = q.where(AuditLog.entity_id == entity_id)
    return db.scalars(q).all()
