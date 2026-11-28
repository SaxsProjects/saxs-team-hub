"""Proposals: generate a first draft from a service preset, edit, issue as SP-PRO, and turn into a quotation."""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..company import company_settings
from ..db import get_db
from ..deps import require_admin
from ..finance import MAX_CENTS, document_totals, line_total
from ..models import Document, LineItem, Proposal, Quotation, User
from ..numbering import allocate_number
from ..proposals import draft_from_preset, preset_list, proposal_pdf
from ..schemas import ORM
from ..schemas_finance import LineIn
from ..services import audit, store_document, today_local
from .finance import _require, _vat_rate, get_client, readiness

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

PDF_TYPE = "application/pdf"
Service = Literal["website", "web_app", "mobile_app", "ecommerce", "automation", "it_support", "custom"]
Text = Field(default=None, max_length=8000)


class ProposalFields(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    introduction: str | None = Text
    need: str | None = Text
    solution: str | None = Text
    scope: str | None = Text
    timeline: str | None = Text
    why_us: str | None = Text
    items: list[LineIn] | None = Field(default=None, max_length=50)


class ProposalIn(ProposalFields):
    client_id: int
    service: Service = "custom"
    title: str = Field(min_length=2, max_length=200)


class GenerateIn(BaseModel):
    client_id: int
    service: Service
    title: str | None = Field(default=None, min_length=2, max_length=200)
    need: str | None = Text


class ProposalItem(BaseModel):
    description: str
    quantity: int
    unit_price_cents: int


class ProposalOut(ORM):
    id: int
    number: str | None
    client_id: int
    title: str
    status: str
    service: str
    introduction: str | None
    need: str | None
    solution: str | None
    scope: str | None
    timeline: str | None
    why_us: str | None
    items: list[ProposalItem]
    vat_rate_bp: int
    subtotal_cents: int
    vat_cents: int
    total_cents: int
    issue_date: date | None
    valid_until: date | None
    quotation_id: int | None
    pdf_sha256: str | None
    created_at: datetime


def get_proposal(db: Session, proposal_id: int) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return p


def _set_items(db: Session, p: Proposal, items: list[LineIn]) -> None:
    clean = []
    for item in items:
        if line_total(item.quantity, item.unit_price_cents) > MAX_CENTS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A line total is too large")
        clean.append(
            {"description": item.description.strip(), "quantity": item.quantity, "unit_price_cents": item.unit_price_cents}
        )
    p.items = clean
    _recalculate(db, p)


def _recalculate(db: Session, p: Proposal) -> None:
    totals = document_totals([i["quantity"] * i["unit_price_cents"] for i in p.items or []], _vat_rate(db))
    if totals.total_cents > MAX_CENTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The total is too large")
    p.vat_rate_bp = _vat_rate(db)
    p.subtotal_cents, p.vat_cents, p.total_cents = totals.subtotal_cents, totals.vat_cents, totals.total_cents


def _apply(db: Session, p: Proposal, body: ProposalFields) -> None:
    changes = body.model_dump(exclude_unset=True, exclude={"items", "client_id", "service"})
    for key, value in changes.items():
        if key == "title" and not value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "title cannot be empty")
        setattr(p, key, value.strip() if isinstance(value, str) else value)
    if body.items is not None:
        _set_items(db, p, body.items)


def _expire_if_past(db: Session, p: Proposal, actor: str) -> bool:
    if p.status == "issued" and p.valid_until and p.valid_until < today_local():
        p.status = "expired"
        audit(db, actor, "proposal.expire", "proposal", p.id)
        return True
    return False


def expire_proposals(db: Session) -> int:
    count = 0
    for p in db.scalars(select(Proposal).where(Proposal.status == "issued", Proposal.valid_until < today_local())):
        count += _expire_if_past(db, p, "system")
    return count


@router.get("/presets")
def presets(_: User = Depends(require_admin)):
    return preset_list()


@router.get("", response_model=list[ProposalOut])
def list_proposals(status_filter: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    stmt = select(Proposal).order_by(Proposal.id.desc())
    if status_filter:
        stmt = stmt.where(Proposal.status == status_filter)
    return db.scalars(stmt).all()


@router.post("", response_model=ProposalOut, status_code=201)
def create_proposal(body: ProposalIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    get_client(db, body.client_id)
    p = Proposal(client_id=body.client_id, service=body.service, title=body.title.strip(), items=[])
    db.add(p)
    _apply(db, p, body)
    _recalculate(db, p)
    db.flush()
    audit(db, admin.email, "proposal.create", "proposal", p.id, after={"service": p.service})
    db.commit()
    return p


@router.post("/generate", response_model=ProposalOut, status_code=201)
def generate_proposal(body: GenerateIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Write a first draft for this client from the service preset. Prices start at R0.00 for the founder to set."""
    client = get_client(db, body.client_id)
    draft = draft_from_preset(body.service, client.name, company_settings(db))
    if body.title:
        draft["title"] = body.title.strip()
    if body.need:
        draft["need"] = body.need.strip()
    items = draft.pop("items")
    p = Proposal(client_id=client.id, **draft, items=items)
    db.add(p)
    _recalculate(db, p)
    db.flush()
    audit(db, admin.email, "proposal.generate", "proposal", p.id, after={"service": body.service})
    db.commit()
    return p


@router.get("/{proposal_id}", response_model=ProposalOut)
def read_proposal(proposal_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return get_proposal(db, proposal_id)


@router.patch("/{proposal_id}", response_model=ProposalOut)
def update_proposal(proposal_id: int, body: ProposalFields, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = get_proposal(db, proposal_id)
    if p.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft proposal can be changed")
    _apply(db, p, body)
    audit(db, admin.email, "proposal.update", "proposal", p.id, after={"fields": sorted(body.model_fields_set)})
    db.commit()
    return p


@router.delete("/{proposal_id}", status_code=204)
def delete_proposal(proposal_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = get_proposal(db, proposal_id)
    if p.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Issued proposals are kept; decline it instead")
    db.delete(p)
    audit(db, admin.email, "proposal.delete", "proposal", proposal_id)
    db.commit()


@router.post("/{proposal_id}/issue", response_model=ProposalOut)
def issue_proposal(proposal_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = get_proposal(db, proposal_id)
    if p.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "This proposal has already been issued")
    if not p.items or p.subtotal_cents <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Price the investment lines first (the total is R0.00)")
    missing = [name for name in ("need", "solution", "scope") if not (getattr(p, name) or "").strip()]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Fill in: {', '.join(missing)}")
    _require(db, readiness(db).can_issue_quotations, "proposals are signed")
    _recalculate(db, p)
    s = company_settings(db)
    today = today_local()
    p.issue_date = today
    p.valid_until = today + timedelta(days=s.proposal_valid_days)
    p.number = allocate_number(db, "PRO")
    p.status = "issued"
    stored = store_document(
        db,
        person_id=None,
        kind="proposal",
        filename=f"{p.number}.pdf",
        content_type=PDF_TYPE,
        content=proposal_pdf(p, draft=False, company=s),
    )
    p.pdf_document_id = stored.id
    p.pdf_sha256 = stored.sha256
    audit(db, admin.email, "proposal.issue", "proposal", p.id, after={"number": p.number, "sha256": stored.sha256})
    db.commit()
    return p


def _respond(db: Session, p: Proposal, new_status: str, actor: str) -> Proposal:
    if _expire_if_past(db, p, actor):
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "This proposal has expired; issue a new one")
    if p.status != "issued":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only an issued proposal can be {new_status} (it is {p.status})")
    p.status = new_status
    audit(db, actor, f"proposal.{new_status}", "proposal", p.id)
    return p


@router.post("/{proposal_id}/accept", response_model=ProposalOut)
def accept_proposal(proposal_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = _respond(db, get_proposal(db, proposal_id), "accepted", admin.email)
    db.commit()
    return p


@router.post("/{proposal_id}/decline", response_model=ProposalOut)
def decline_proposal(proposal_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = _respond(db, get_proposal(db, proposal_id), "declined", admin.email)
    db.commit()
    return p


@router.post("/{proposal_id}/quotation", response_model=ProposalOut)
def make_quotation(proposal_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Create a draft quotation with the proposal's price lines (once). Issue it from Client finance."""
    p = get_proposal(db, proposal_id)
    if p.status not in ("issued", "accepted"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Issue the proposal first")
    if p.quotation_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "A quotation was already made from this proposal")
    q = Quotation(client_id=p.client_id, title=p.title, notes=f"From proposal {p.number}")
    db.add(q)
    for position, item in enumerate(p.items, start=1):
        q.lines.append(
            LineItem(
                position=position,
                description=item["description"],
                quantity=item["quantity"],
                unit_price_cents=item["unit_price_cents"],
                line_total_cents=item["quantity"] * item["unit_price_cents"],
            )
        )
    totals = document_totals([line.line_total_cents for line in q.lines], _vat_rate(db))
    q.vat_rate_bp = _vat_rate(db)
    q.subtotal_cents, q.vat_cents, q.total_cents = totals.subtotal_cents, totals.vat_cents, totals.total_cents
    db.flush()
    p.quotation_id = q.id
    if p.status == "issued":
        p.status = "accepted"
    audit(db, admin.email, "proposal.quotation", "proposal", p.id, after={"quotation_id": q.id})
    audit(db, admin.email, "quotation.create", "quotation", q.id, after={"from_proposal": p.number})
    db.commit()
    return p


@router.get("/{proposal_id}/pdf")
def proposal_pdf_file(proposal_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    p = get_proposal(db, proposal_id)
    if p.pdf_document_id:
        doc = db.get(Document, p.pdf_document_id)
        content = doc.content
    else:
        content = proposal_pdf(p, draft=True, company=company_settings(db))
    name = f"{p.number or 'proposal-draft'}.pdf"
    return Response(content, media_type=PDF_TYPE, headers={"Content-Disposition": f'inline; filename="{name}"'})
