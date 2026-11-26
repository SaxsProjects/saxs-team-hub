from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..avatars import avatar_url
from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..emailer import OutgoingEmail, send_email
from ..models import INITIAL_RATE_BP, STAGES, Document, OnboardingItem, Person, RatePeriod, User
from ..schemas import (
    AccessIn,
    DocumentOut,
    OnboardingItemOut,
    OnboardingUpdate,
    PersonCreate,
    PersonOut,
    PersonUpdate,
    RatePeriodOut,
    SensitiveIn,
    StageIn,
)
from ..security import decrypt_json, encrypt_json
from ..services import (
    MANUAL_STAGE_MOVES,
    audit,
    complete_onboarding_item,
    issue_action_token,
    link,
    revoke_sessions,
    set_stage,
    store_document,
    today_local,
)
from ..terms import rate_at

router = APIRouter(prefix="/api", tags=["people"])


def current_rate(p: Person) -> int:
    today = today_local()
    started = [r for r in p.rate_periods if r.effective_from <= today]
    return max(started, key=lambda r: r.effective_from).rate_bp if started else INITIAL_RATE_BP


def person_out(p: Person) -> PersonOut:
    out = PersonOut.model_validate(p)
    out.rate_bp = current_rate(p)  # from the rate history, so a review dated ahead takes effect on its date
    out.has_sensitive_details = bool(p.sensitive_enc)
    out.avatar_url = avatar_url(p.account)
    return out


def get_person(db: Session, person_id: int) -> Person:
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    return person


@router.get("/people", response_model=list[PersonOut])
def list_people(stage: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    q = select(Person).order_by(Person.created_at.desc())
    if stage:
        q = q.where(Person.status == stage)
    return [person_out(p) for p in db.scalars(q)]


@router.post("/people", response_model=PersonOut, status_code=201)
def create_person(body: PersonCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    person = Person(full_name=body.full_name.strip(), email=body.email.lower(), phone=body.phone)
    db.add(person)
    db.flush()
    audit(db, admin.email, "person.create", "person", person.id, after={"stage": person.status})
    db.commit()
    return person_out(person)


@router.get("/people/{person_id}", response_model=PersonOut)
def read_person(person_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return person_out(get_person(db, person_id))


@router.patch("/people/{person_id}", response_model=PersonOut)
def update_person(person_id: int, body: PersonUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    person = get_person(db, person_id)
    changes = body.model_dump(exclude_unset=True)
    new_rate = changes.pop("rate_bp", None)
    note = changes.pop("rate_review_note", None)
    effective_from = changes.pop("rate_effective_from", None) or today_local()
    before = {"rate_bp": current_rate(person), "fee_terms": person.fee_terms}
    if new_rate is not None:
        rate_then = rate_at(db, person.id, effective_from)
        if new_rate == rate_then:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"The rate on {effective_from} is already {new_rate / 100:g}%. To withdraw a change dated ahead, "
                "use DELETE /api/people/{id}/rates/{period_id}",
            )
        if not (note and note.strip()):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Changing the rate needs rate_review_note (the written review it is based on)"
            )
        if any(r.effective_from == effective_from for r in person.rate_periods):
            raise HTTPException(status.HTTP_409_CONFLICT, f"A rate change dated {effective_from} is already recorded")
        period = RatePeriod(
            person_id=person.id, rate_bp=new_rate, effective_from=effective_from, review_note=note.strip(), created_by=admin.email
        )
        person.rate_periods.append(period)
        db.flush()
        person.rate_review_note = note.strip()
        person.rate_bp = current_rate(person)
        audit(
            db,
            admin.email,
            "person.rate_change",
            "person",
            person.id,
            {"rate_bp": rate_then},
            {"rate_bp": new_rate, "effective_from": str(effective_from), "rate_period_id": period.id},
        )
    for key, value in changes.items():
        setattr(person, key, value.lower() if key == "email" and value else value)
    audit(
        db,
        admin.email,
        "person.update",
        "person",
        person.id,
        before,
        {"fields": sorted(body.model_dump(exclude_unset=True)), "rate_bp": current_rate(person), "fee_terms": person.fee_terms},
    )
    db.commit()
    return person_out(person)


@router.get("/people/{person_id}/rates", response_model=list[RatePeriodOut])
def rate_history(person_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Every recorded rate change, oldest first. Before the first one the initial 15% applies."""
    return get_person(db, person_id).rate_periods


@router.delete("/people/{person_id}/rates/{period_id}", status_code=204)
def withdraw_future_rate(person_id: int, period_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Withdraw a rate change that has not started yet. Changes already in force are history and stay."""
    period = db.get(RatePeriod, period_id)
    if not period or period.person_id != person_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rate change not found")
    if period.effective_from <= today_local():
        raise HTTPException(status.HTTP_409_CONFLICT, "This rate is already in force; record a new rate change instead")
    person = get_person(db, person_id)
    withdrawn = {"rate_bp": period.rate_bp, "effective_from": str(period.effective_from)}
    person.rate_periods.remove(period)
    db.flush()
    person.rate_bp = current_rate(person)
    audit(db, admin.email, "person.rate_withdraw", "person", person_id, withdrawn)
    db.commit()


@router.delete("/people/{person_id}", status_code=204)
def delete_person(person_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Erase a person's data (POPIA). Not allowed once they have payout records."""
    person = get_person(db, person_id)
    from ..models import Payout, ProjectContributor, TaskOrder

    if (
        db.scalar(select(Payout.id).where(Payout.person_id == person.id).limit(1))
        or db.scalar(select(ProjectContributor.id).where(ProjectContributor.person_id == person.id).limit(1))
        or db.scalar(select(TaskOrder.id).where(TaskOrder.person_id == person.id).limit(1))
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This person has project or payout records that must be kept for tax purposes"
        )
    for user in db.scalars(select(User).where(User.person_id == person.id)):
        db.delete(user)
    db.delete(person)
    audit(db, admin.email, "person.erase", "person", person_id)
    db.commit()


@router.post("/people/{person_id}/stage", response_model=PersonOut)
def move_stage(person_id: int, body: StageIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    person = get_person(db, person_id)
    if body.stage not in STAGES or MANUAL_STAGE_MOVES.get(person.status) != body.stage:
        allowed = MANUAL_STAGE_MOVES.get(person.status)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Can't move from '{person.status}' to '{body.stage}'" + (f"; next step is '{allowed}'" if allowed else ""),
        )
    set_stage(db, person, body.stage, admin.email)
    if body.stage == "agreement_signed":
        complete_onboarding_item(db, person, "agreement_signed")
    db.commit()
    return person_out(person)


# ---- Sensitive details (encrypted) -------------------------------------------------


def mask(details: dict) -> dict:
    out = dict(details)
    acct = out.get("account_number", "").replace(" ", "")
    out["account_number"] = f"****{acct[-4:]}" if acct else ""
    if out.get("id_number"):
        out["id_number"] = f"****{out['id_number'][-3:]}"
    return out


def save_sensitive(db: Session, person: Person, body: SensitiveIn, actor: str) -> None:
    person.sensitive_enc = encrypt_json(body.model_dump())
    complete_onboarding_item(db, person, "banking_captured")
    audit(db, actor, "person.sensitive_update", "person", person.id, after={"fields": sorted(body.model_dump())})


@router.put("/people/{person_id}/sensitive", status_code=204)
def put_sensitive(person_id: int, body: SensitiveIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    save_sensitive(db, get_person(db, person_id), body, admin.email)
    db.commit()


@router.get("/people/{person_id}/sensitive")
def get_sensitive(person_id: int, reveal: bool = False, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    person = get_person(db, person_id)
    details = decrypt_json(person.sensitive_enc)
    if details is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No details captured")
    if reveal:
        audit(db, admin.email, "person.sensitive_reveal", "person", person.id)
        db.commit()
        return details
    return mask(details)


# ---- Onboarding (admin) -------------------------------------------------------------


@router.get("/people/{person_id}/onboarding", response_model=list[OnboardingItemOut])
def person_onboarding(person_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return get_person(db, person_id).onboarding_items


@router.patch("/onboarding/{item_id}", response_model=OnboardingItemOut)
def update_onboarding(item_id: int, body: OnboardingUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    item = db.get(OnboardingItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist item not found")
    item.done = body.done
    item.done_at = datetime.now(UTC) if body.done else None
    audit(db, admin.email, "onboarding.update", "onboarding_item", item.id, after={"key": item.key, "done": body.done})
    db.commit()
    return item


# ---- Documents (admin upload, e.g. signed contractor agreement) -----------------------

ALLOWED_UPLOAD_KINDS = {"agreement", "other"}


async def read_pdf_upload(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File is larger than {limit // 1048576} MB")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files are accepted")
    return data


@router.post("/people/{person_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    person_id: int,
    kind: str = "agreement",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if kind not in ALLOWED_UPLOAD_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"kind must be one of {sorted(ALLOWED_UPLOAD_KINDS)}")
    person = get_person(db, person_id)
    data = await read_pdf_upload(file)
    doc = store_document(
        db, person_id=person.id, kind=kind, filename=file.filename or f"{kind}.pdf", content_type="application/pdf", content=data
    )
    audit(db, admin.email, "document.upload", "document", doc.id, after={"kind": kind, "sha256": doc.sha256})
    if kind == "agreement":
        complete_onboarding_item(db, person, "agreement_signed")
    db.commit()
    return doc


@router.get("/people/{person_id}/documents", response_model=list[DocumentOut])
def list_documents(person_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(
        select(Document).where(Document.person_id == get_person(db, person_id).id).order_by(Document.created_at)
    ).all()


# ---- Team member accounts -------------------------------------------------------------


def member_account(db: Session, person: Person) -> User:
    user = db.scalar(select(User).where(User.person_id == person.id, User.role == "member"))
    if not user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This person has no Team Hub account yet (it is created when they accept an offer)"
        )
    return user


@router.post("/people/{person_id}/invite", status_code=204)
def resend_invite(
    person_id: int, background: BackgroundTasks, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    """Email a fresh 7-day set-password link (older links stop working)."""
    person = get_person(db, person_id)
    user = member_account(db, person)
    if not user.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Turn this person's access back on first")
    token = issue_action_token(db, user, "set_password", timedelta(days=7))
    audit(db, admin.email, "user.invite_resent", "user", user.id)
    db.commit()
    settings = get_settings()
    background.add_task(
        send_email,
        OutgoingEmail(
            to=user.email,
            subject=f"Your {settings.company_name} Team Hub account",
            text=(
                f"Hi {person.full_name},\n\nSet your Team Hub password here (valid for 7 days):\n"
                f"{link('/set-password?token=' + token)}\n\n{settings.company_name}"
            ),
        ),
    )


@router.post("/people/{person_id}/access", response_model=PersonOut)
def set_access(person_id: int, body: AccessIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Turn a team member's sign-in on or off (offboarding). Turning it off signs them out everywhere."""
    person = get_person(db, person_id)
    user = member_account(db, person)
    user.is_active = body.active
    if not body.active:
        revoke_sessions(user)
    audit(db, admin.email, "user.access", "user", user.id, after={"active": body.active})
    db.commit()
    return person_out(person)
