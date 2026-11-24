"""What a signed-in team member can see: only their own data."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require_admin, require_member
from ..models import AuditLog, Document, OnboardingItem, Payout, ProjectContributor, User
from ..schemas import AuditOut, DocumentOut, OnboardingItemOut, OnboardingUpdate, PayoutOut, PersonOut, SensitiveIn
from ..security import decrypt_json
from ..services import audit
from .people import mask, person_out, save_sensitive

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
            "rate_bp": c.rate_bp,
            "locked_at": c.locked_at,
        }
        for c in rows
    ]


@router.get("/me/payouts", response_model=list[PayoutOut])
def my_payouts(db: Session = Depends(get_db), user: User = Depends(require_member)):
    return db.scalars(select(Payout).where(Payout.person_id == user.person_id).order_by(Payout.due_at)).all()


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
