"""Offers: admin side (create, attach PDF, send, revoke) and the candidate's public link."""

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import client_ip, public_offer_limiter, require_admin
from ..emailer import OutgoingEmail, notify_admin, send_email
from ..models import Offer, OfferResponse, Person, User
from ..pdf import acceptance_record_pdf
from ..schemas import (
    AcceptIn,
    DeclineIn,
    OfferCreate,
    OfferOut,
    OfferSentOut,
    OfferUpdate,
    PublicOfferOut,
)
from ..security import canonical_hash, hash_token, new_token
from ..services import (
    audit,
    end_of_day_utc,
    ensure_onboarding,
    issue_action_token,
    link,
    set_stage,
    store_document,
    today_local,
)
from .people import get_person, read_pdf_upload

INVITE_VALID_FOR = timedelta(days=7)

router = APIRouter(prefix="/api", tags=["offers"])
public = APIRouter(prefix="/api/public/offers", tags=["public offers"], dependencies=[Depends(public_offer_limiter)])

PRIVACY_NOTICE = (
    "We use your name, contact details and your response to this offer only to manage your engagement with "
    "{company}, as required by the Protection of Personal Information Act (POPIA). If you decline, we delete "
    "your details after {days} days. Your information is stored encrypted with our service providers in "
    "Frankfurt, Germany (European Union), whose data-protection law is at least as strong as POPIA (section 72). "
    "You may ask us to access, correct or delete your information at any time."
)


def offer_out(offer: Offer, cls=OfferOut, **extra) -> OfferOut:
    data = cls.model_validate(
        {
            **{c: getattr(offer, c) for c in OfferOut.model_fields if hasattr(offer, c)},
            "has_pdf": offer.pdf_document_id is not None,
            **extra,
        }
    )
    data.overdue = offer.status in ("sent", "viewed") and offer.deadline < today_local()
    return data


def get_offer(db: Session, offer_id: int) -> Offer:
    offer = db.get(Offer, offer_id)
    if not offer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    return offer


def offer_version_hash(offer: Offer) -> str:
    return canonical_hash(
        {
            "reference": offer.reference,
            "role": offer.role,
            "candidate": offer.person.full_name,
            "deadline": offer.deadline.isoformat(),
            "message": offer.message or "",
            "pdf_sha256": offer.pdf_document.sha256 if offer.pdf_document else None,
        }
    )


def next_reference(db: Session) -> str:
    year = today_local().year
    count = db.scalar(select(func.count(Offer.id)).where(Offer.reference.like(f"SP-OFF-{year}-%"))) or 0
    return f"SP-OFF-{year}-{count + 1:03d}"


# ---- Admin ------------------------------------------------------------------------------


@router.get("/offers", response_model=list[OfferOut])
def list_offers(status_filter: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    q = select(Offer).order_by(Offer.created_at.desc())
    if status_filter:
        q = q.where(Offer.status == status_filter)
    return [offer_out(o) for o in db.scalars(q)]


@router.post("/offers", response_model=OfferOut, status_code=201)
def create_offer(body: OfferCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    person = get_person(db, body.person_id)
    if body.deadline < today_local():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The deadline is in the past")
    reference = (body.reference or next_reference(db)).strip()
    if db.scalar(select(Offer.id).where(Offer.reference == reference)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That reference is already used")
    offer = Offer(person_id=person.id, role=body.role.strip(), reference=reference, deadline=body.deadline, message=body.message)
    db.add(offer)
    db.flush()
    audit(db, admin.email, "offer.create", "offer", offer.id, after={"reference": reference, "status": "draft"})
    db.commit()
    return offer_out(offer)


@router.get("/offers/{offer_id}", response_model=OfferOut)
def read_offer(offer_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return offer_out(get_offer(db, offer_id))


@router.patch("/offers/{offer_id}", response_model=OfferOut)
def update_offer(offer_id: int, body: OfferUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    offer = get_offer(db, offer_id)
    if offer.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only draft offers can be edited; revoke and create a new one")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(offer, key, value)
    audit(db, admin.email, "offer.update", "offer", offer.id, after={"fields": sorted(body.model_dump(exclude_unset=True))})
    db.commit()
    return offer_out(offer)


@router.post("/offers/{offer_id}/pdf", response_model=OfferOut)
async def attach_pdf(
    offer_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    offer = get_offer(db, offer_id)
    if offer.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "The PDF can only be changed while the offer is a draft")
    data = await read_pdf_upload(file)
    doc = store_document(
        db,
        person_id=offer.person_id,
        kind="offer_pdf",
        filename=file.filename or f"{offer.reference}.pdf",
        content_type="application/pdf",
        content=data,
    )
    offer.pdf_document_id = doc.id
    audit(db, admin.email, "offer.attach_pdf", "offer", offer.id, after={"document_id": doc.id, "sha256": doc.sha256})
    db.commit()
    return offer_out(offer)


@router.post("/offers/{offer_id}/send", response_model=OfferSentOut)
def send_offer(offer_id: int, background: BackgroundTasks, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Create the candidate's personal link and email it. Sending again replaces the old link."""
    offer = get_offer(db, offer_id)
    if offer.status not in ("draft", "sent", "viewed"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Offer is {offer.status}; create a new offer instead")
    if offer.pdf_document_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Attach the proposal PDF before sending")
    if offer.deadline < today_local():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The deadline has passed; revoke this offer and create a new one")

    token = new_token()
    offer.token_hash = hash_token(token)
    offer.token_expires_at = end_of_day_utc(offer.deadline)
    offer.offer_hash = offer_version_hash(offer)
    first_send = offer.status == "draft"
    offer.status = "sent" if first_send else offer.status
    offer.sent_at = datetime.now(UTC)
    if first_send:
        set_stage(db, offer.person, "sent", admin.email)
    audit(
        db,
        admin.email,
        "offer.send" if first_send else "offer.resend",
        "offer",
        offer.id,
        after={"status": offer.status, "offer_hash": offer.offer_hash},
    )
    db.commit()

    settings = get_settings()
    offer_link = link(f"/offer/{token}")
    background.add_task(
        send_email,
        OutgoingEmail(
            to=offer.person.email,
            subject=f"Your offer from {settings.company_name}: {offer.role} ({offer.reference})",
            text=(
                f"Hi {offer.person.full_name},\n\n"
                f"{settings.company_name} would like to offer you the role of {offer.role}.\n\n"
                f"Read the offer and accept or decline here (this link is personal to you):\n{offer_link}\n\n"
                f"Please respond by {offer.deadline:%d %B %Y}.\n\n"
                f"Kind regards,\n{settings.company_name}"
            ),
            reply_to=settings.admin_notify_email or None,
        ),
    )
    return offer_out(offer, OfferSentOut, offer_link=offer_link)


@router.post("/offers/{offer_id}/revoke", response_model=OfferOut)
def revoke_offer(offer_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    offer = get_offer(db, offer_id)
    if offer.status in ("accepted", "declined"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Offer was already {offer.status}")
    offer.status = "revoked"
    offer.token_hash = None
    audit(db, admin.email, "offer.revoke", "offer", offer.id, after={"status": "revoked"})
    db.commit()
    return offer_out(offer)


@router.get("/pipeline")
def pipeline(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Board view: every person grouped by stage, with their latest offer."""
    from ..models import STAGES

    board: dict[str, list] = {stage: [] for stage in STAGES}
    overdue = 0
    for person in db.scalars(select(Person).order_by(Person.updated_at.desc())):
        latest = max(person.offers, key=lambda o: o.created_at, default=None)
        latest_out = offer_out(latest).model_dump(mode="json") if latest else None
        overdue += bool(latest_out and latest_out["overdue"])
        board.setdefault(person.status, []).append(
            {
                "person_id": person.id,
                "full_name": person.full_name,
                "email": person.email,
                "offer": latest_out,
            }
        )
    return {"stages": board, "overdue_count": overdue}


# ---- Candidate (public link) ------------------------------------------------------------


def expire_offer(db: Session, offer: Offer, actor: str = "system") -> None:
    offer.status = "expired"
    set_stage(db, offer.person, "expired", actor)
    audit(db, actor, "offer.expire", "offer", offer.id, after={"status": "expired"})
    if not offer.expired_notified_at:
        offer.expired_notified_at = datetime.now(UTC)
        notify_admin(
            f"Offer expired: {offer.reference}",
            f"The offer {offer.reference} ({offer.role}) to {offer.person.full_name} passed its deadline "
            f"of {offer.deadline:%d %B %Y} without a response.",
        )


def resolve_token(db: Session, token: str) -> Offer:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    offer = db.scalar(select(Offer).where(Offer.token_hash == hash_token(token)))
    if not offer or offer.status == "revoked":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    if offer.status in ("sent", "viewed") and offer.token_expires_at and datetime.now(UTC) > offer.token_expires_at:
        expire_offer(db, offer)
        db.commit()
    return offer


def public_out(offer: Offer) -> PublicOfferOut:
    settings = get_settings()
    return PublicOfferOut(
        reference=offer.reference,
        role=offer.role,
        candidate_name=offer.person.full_name,
        deadline=offer.deadline,
        message=offer.message,
        status=offer.status,
        has_pdf=offer.pdf_document_id is not None,
        company_name=settings.company_name,
        privacy_notice=PRIVACY_NOTICE.format(company=settings.company_name, days=settings.declined_retention_days),
        can_respond=offer.status in ("sent", "viewed"),
    )


@public.get("/{token}", response_model=PublicOfferOut)
def view_offer(token: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    offer = resolve_token(db, token)
    if offer.status == "sent":
        offer.status = "viewed"
        offer.viewed_at = datetime.now(UTC)
        set_stage(db, offer.person, "viewed", "candidate")
        audit(db, "candidate", "offer.view", "offer", offer.id, after={"status": "viewed"})
        db.commit()
        background.add_task(
            notify_admin,
            f"Offer viewed: {offer.reference}",
            f"{offer.person.full_name} opened the offer {offer.reference} ({offer.role}).",
        )
    return public_out(offer)


@public.get("/{token}/pdf")
def offer_pdf(token: str, db: Session = Depends(get_db)):
    offer = resolve_token(db, token)
    if not offer.pdf_document:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF attached")
    doc = offer.pdf_document
    return Response(
        doc.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{offer.reference}.pdf"',
            "X-Content-SHA256": doc.sha256,
        },
    )


def _normalise_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _ensure_open(offer: Offer) -> None:
    if offer.status == "expired":
        raise HTTPException(status.HTTP_410_GONE, "This offer has expired. Please contact us if you are still interested.")
    if offer.status not in ("sent", "viewed") or offer.response:
        raise HTTPException(status.HTTP_409_CONFLICT, "This offer has already been answered")


@public.post("/{token}/accept", response_model=PublicOfferOut)
def accept_offer(token: str, body: AcceptIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    offer = resolve_token(db, token)
    _ensure_open(offer)
    person = offer.person
    if not body.agree:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please tick the box to confirm you accept the offer")
    if _normalise_name(body.typed_signature) != _normalise_name(person.full_name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Type your full name exactly as shown on the offer: {person.full_name}")
    current_hash = offer_version_hash(offer)
    if current_hash != offer.offer_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "This offer has changed since it was sent. Please contact us.")

    now = datetime.now(UTC)
    ip = client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:512]
    record = acceptance_record_pdf(
        reference=offer.reference,
        role=offer.role,
        full_name=person.full_name,
        typed_signature=body.typed_signature.strip(),
        responded_at=now,
        ip=ip,
        user_agent=ua,
        offer_hash=current_hash,
        pdf_sha256=offer.pdf_document.sha256 if offer.pdf_document else None,
    )
    acceptance_doc = store_document(
        db,
        person_id=person.id,
        kind="acceptance",
        filename=f"{offer.reference}-acceptance.pdf",
        content_type="application/pdf",
        content=record,
    )
    db.add(
        OfferResponse(
            offer_id=offer.id,
            decision="accepted",
            typed_signature=body.typed_signature.strip(),
            ip=ip,
            user_agent=ua,
            offer_hash=current_hash,
            acceptance_document_id=acceptance_doc.id,
            responded_at=now,
        )
    )
    offer.status = "accepted"
    offer.responded_at = now
    set_stage(db, person, "accepted", "candidate")
    db.flush()
    db.refresh(person)
    ensure_onboarding(db, person)

    # Team member account: they choose their own password from an emailed link.
    settings = get_settings()
    setup_link = None
    user = db.scalar(select(User).where(User.email == person.email))
    if user is None:
        user = User(email=person.email, role="member", person_id=person.id)
        db.add(user)
        db.flush()
    if user.role == "member":
        user.person_id = person.id
        setup_token = issue_action_token(db, user, "set_password", INVITE_VALID_FOR)
        setup_link = link(f"/set-password?token={setup_token}")
    audit(
        db,
        "candidate",
        "offer.accept",
        "offer",
        offer.id,
        after={"status": "accepted", "offer_hash": current_hash, "acceptance_document_id": acceptance_doc.id},
    )
    db.commit()

    background.add_task(
        notify_admin,
        f"Offer ACCEPTED: {offer.reference}",
        f"{person.full_name} accepted the offer {offer.reference} ({offer.role}) at "
        f"{now:%Y-%m-%d %H:%M} UTC. Their onboarding checklist has been created.",
    )
    background.add_task(
        send_email,
        OutgoingEmail(
            to=person.email,
            subject=f"Welcome to {settings.company_name} - offer {offer.reference} accepted",
            text=(
                f"Hi {person.full_name},\n\nThank you for accepting the role of {offer.role}. "
                "A copy of your acceptance record is attached.\n\n"
                + (f"Set your Team Hub password here (valid for 7 days):\n{setup_link}\n\n" if setup_link else "")
                + f"We'll be in touch about next steps.\n\n{settings.company_name}"
            ),
            attachments=[(f"{offer.reference}-acceptance.pdf", record, "application/pdf")],
        ),
    )
    return public_out(offer)


@public.post("/{token}/decline", response_model=PublicOfferOut)
def decline_offer(token: str, body: DeclineIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    offer = resolve_token(db, token)
    _ensure_open(offer)
    now = datetime.now(UTC)
    db.add(
        OfferResponse(
            offer_id=offer.id,
            decision="declined",
            reason=(body.reason or "").strip() or None,
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:512],
            offer_hash=offer.offer_hash or offer_version_hash(offer),
            responded_at=now,
        )
    )
    offer.status = "declined"
    offer.responded_at = now
    set_stage(db, offer.person, "declined", "candidate")
    audit(db, "candidate", "offer.decline", "offer", offer.id, after={"status": "declined"})
    db.commit()

    settings = get_settings()
    reason = f"\n\nReason given: {body.reason.strip()}" if body.reason and body.reason.strip() else ""
    background.add_task(
        notify_admin,
        f"Offer declined: {offer.reference}",
        f"{offer.person.full_name} declined the offer {offer.reference} ({offer.role}).{reason}",
    )
    background.add_task(
        send_email,
        OutgoingEmail(
            to=offer.person.email,
            subject=f"Thank you for your response - {settings.company_name}",
            text=(
                f"Hi {offer.person.full_name},\n\nThank you for letting us know, and for considering {settings.company_name}. "
                "We wish you every success and hope our paths cross again.\n\n"
                f"As promised in our privacy notice, we will delete your details after "
                f"{settings.declined_retention_days} days.\n\n{settings.company_name}"
            ),
        ),
    )
    return public_out(offer)
