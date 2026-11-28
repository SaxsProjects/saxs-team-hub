"""Integration API for other SaxsProjects systems (SAXI-OS): the Team Hub stays the system of record for money.

A key is made by the founder (two-factor required), shown once, stored only as a SHA-256 hash, and limited to
scopes. Keys can read clients, quotations, invoices and enquiries and save *draft* proposals. Nothing here can
issue a document, record a payment, change a payout or move money: those actions stay with the founder in the
hub. Every draft a system saves rings the founder's bell and is in the audit history under the key's name.

No personal information leaves the hub through this API (POPIA s19, data minimisation): no names, email
addresses, phone numbers, addresses, contact people, free-text messages, document titles, notes or line
descriptions. Other systems may pass what they read to outside AI services, so they get IDs, statuses,
dates and amounts only. The founder sees the full record in the hub.
"""

import secrets
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import RateLimiter, require_admin
from ..models import ApiKey, Client, Enquiry, Invoice, Proposal, Quotation, User
from ..notifications import notify_admins
from ..security import hash_token
from ..services import audit
from .finance import get_client, invoice_out
from .proposals import ProposalFields, Service, _apply, _recalculate

Scope = Literal["clients:read", "quotations:read", "invoices:read", "enquiries:read", "proposals:draft"]
SCOPES: tuple[str, ...] = Scope.__args__
KEY_PREFIX = "sphub_"

admin_router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])
router = APIRouter(prefix="/api/integrations/v1", tags=["integrations"])
key_limiter = RateLimiter(120, 60, "integration-key")


# ---- Founder: manage keys ---------------------------------------------------------------------------------


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    scopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))


class ApiKeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[str]
    created_by: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def of(cls, k: ApiKey) -> "ApiKeyOut":
        return cls(**{f: getattr(k, f) for f in cls.model_fields})


class NewApiKeyOut(ApiKeyOut):
    key: str  # shown once


@admin_router.get("", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [ApiKeyOut.of(k) for k in db.scalars(select(ApiKey).order_by(ApiKey.id.desc()))]


@admin_router.post("", response_model=NewApiKeyOut, status_code=201)
def create_key(body: ApiKeyIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    k = ApiKey(
        name=body.name.strip(), prefix=raw[:12], key_hash=hash_token(raw), scopes=sorted(set(body.scopes)), created_by=admin.email
    )
    db.add(k)
    db.flush()
    audit(db, admin.email, "api_key.create", "api_key", k.id, after={"name": k.name, "scopes": k.scopes})
    db.commit()
    return NewApiKeyOut(**ApiKeyOut.of(k).model_dump(), key=raw)


@admin_router.post("/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_key(key_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    k = db.get(ApiKey, key_id)
    if not k:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    if k.revoked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This key is already revoked")
    k.revoked_at = utcnow()
    audit(db, admin.email, "api_key.revoke", "api_key", k.id, after={"name": k.name})
    db.commit()
    return ApiKeyOut.of(k)


# ---- Systems: use a key ------------------------------------------------------------------------------------


def require_scope(scope: str):
    def check(request: Request, x_api_key: str = Header(default="", alias="X-Api-Key"), db: Session = Depends(get_db)) -> ApiKey:
        key_limiter(request)
        bad = HTTPException(status.HTTP_401_UNAUTHORIZED, "A valid API key is required")
        if not x_api_key.startswith(KEY_PREFIX) or len(x_api_key) > 100:
            raise bad
        k = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_token(x_api_key)))
        if not k or k.revoked_at:
            raise bad
        if scope not in (k.scopes or []):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This key does not have the {scope} scope")
        k.last_used_at = utcnow()
        db.commit()
        return k

    return check


# ---- Outputs: IDs, statuses, dates and amounts only. Never personal information. ----------------------------


class HubClient(BaseModel):
    id: int
    kind: str
    label: str  # "Client 12"; the real name stays in the hub
    created_at: datetime


class HubDocument(BaseModel):
    id: int
    number: str | None
    client_id: int
    project_id: int | None
    status: str
    issue_date: date | None
    subtotal_cents: int
    vat_cents: int
    total_cents: int


class HubInvoice(HubDocument):
    due_date: date | None
    paid_cents: int
    credited_cents: int
    balance_cents: int
    overdue: bool


class HubEnquiry(BaseModel):
    id: int
    service: str | None
    source: str
    status: str
    client_id: int | None
    created_at: datetime


class HubProposal(BaseModel):
    id: int
    client_id: int
    status: str
    service: str


def _doc(d) -> dict:
    return {f: getattr(d, f) for f in HubDocument.model_fields}


@router.get("/clients", response_model=list[HubClient])
def api_clients(db: Session = Depends(get_db), _: ApiKey = Depends(require_scope("clients:read"))):
    rows = db.scalars(select(Client).order_by(Client.id)).all()
    return [HubClient(id=c.id, kind=c.kind, label=f"Client {c.id}", created_at=c.created_at) for c in rows]


@router.get("/quotations", response_model=list[HubDocument])
def api_quotations(db: Session = Depends(get_db), _: ApiKey = Depends(require_scope("quotations:read"))):
    rows = db.scalars(select(Quotation).order_by(Quotation.created_at.desc()).limit(500))
    return [HubDocument(**_doc(q)) for q in rows]


@router.get("/invoices", response_model=list[HubInvoice])
def api_invoices(db: Session = Depends(get_db), _: ApiKey = Depends(require_scope("invoices:read"))):
    out = []
    for i in db.scalars(select(Invoice).order_by(Invoice.created_at.desc()).limit(500)):
        full = invoice_out(i)
        out.append(HubInvoice(**{f: getattr(full, f) for f in HubInvoice.model_fields}))
    return out


@router.get("/enquiries", response_model=list[HubEnquiry])
def api_enquiries(db: Session = Depends(get_db), _: ApiKey = Depends(require_scope("enquiries:read"))):
    rows = db.scalars(select(Enquiry).order_by(Enquiry.created_at.desc()).limit(500))
    return [HubEnquiry(**{f: getattr(e, f) for f in HubEnquiry.model_fields}) for e in rows]


class DraftProposalIn(ProposalFields):
    client_id: int
    service: Service = "custom"
    title: str = Field(min_length=2, max_length=200)


@router.post("/proposals", response_model=HubProposal, status_code=201)
def api_draft_proposal(
    body: DraftProposalIn, db: Session = Depends(get_db), key: ApiKey = Depends(require_scope("proposals:draft"))
):
    """Save a draft proposal for the founder to review, price and issue in the hub. It is never issued from here."""
    get_client(db, body.client_id)
    p = Proposal(client_id=body.client_id, service=body.service, title=body.title.strip(), items=[])
    db.add(p)
    _apply(db, p, body)
    _recalculate(db, p)
    db.flush()
    actor = f"api:{key.name}"
    audit(db, actor, "proposal.draft_from_api", "proposal", p.id, after={"service": p.service, "key_id": key.id})
    notify_admins(db, "system", f"Draft proposal from {key.name}", p.title, f"/proposals?open={p.id}")
    db.commit()
    return HubProposal(id=p.id, client_id=p.client_id, status=p.status, service=p.service)
