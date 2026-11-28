"""Enquiries from the company website's contact form, and the founder's follow-up.

The website posts as a "simple" cross-origin request (Content-Type text/plain, no cookies), so no CORS
preflight is needed and the hub's main CORS list (which allows the sign-in cookie) stays limited to the
hub itself. Only the website origins get an Access-Control-Allow-Origin header back, without credentials.
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import RateLimiter, require_admin
from ..emailer import notify_admin
from ..models import Client, Enquiry, User
from ..services import audit

router = APIRouter(tags=["enquiries"])

enquiry_limiter = RateLimiter(5, 600, "website-enquiry")
MAX_BODY = 16_000
EnquiryStatus = Literal["new", "contacted", "converted", "closed"]


class EnquiryIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str = Field(min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=40)
    organisation: str | None = Field(None, max_length=200)
    service: str | None = Field(None, max_length=120)
    message: str = Field(min_length=5, max_length=5000)
    # Honeypot: a field people never see. Bots fill it in; such posts are accepted and dropped.
    website: str | None = Field(None, max_length=500)


class EnquiryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None
    phone: str | None
    organisation: str | None
    service: str | None
    message: str
    source: str
    status: EnquiryStatus
    client_id: int | None
    created_at: str

    @classmethod
    def of(cls, e: Enquiry) -> "EnquiryOut":
        return cls(**{k: getattr(e, k) for k in cls.model_fields if k != "created_at"}, created_at=e.created_at.isoformat())


class EnquiryUpdate(BaseModel):
    status: EnquiryStatus


def _cors(request: Request, response: JSONResponse) -> JSONResponse:
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin in get_settings().website_origin_list:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


@router.post("/api/public/enquiries", dependencies=[Depends(enquiry_limiter)])
async def website_enquiry(request: Request, db: Session = Depends(get_db)):
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin and origin not in get_settings().website_origin_list:
        return JSONResponse({"detail": "Not allowed"}, status_code=403)
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return _cors(request, JSONResponse({"detail": "Message too long"}, status_code=413))
    try:
        data = EnquiryIn.model_validate(json.loads(raw or b"{}"))
    except (ValueError, ValidationError):
        return _cors(
            request, JSONResponse({"detail": "Please give your name, a way to reach you and a message."}, status_code=422)
        )
    if not data.email and not data.phone:
        return _cors(request, JSONResponse({"detail": "Please give an email address or a phone number."}, status_code=422))
    if data.website:  # honeypot
        return _cors(request, JSONResponse({"ok": True}, status_code=201))

    e = Enquiry(**data.model_dump(exclude={"website"}), source="website")
    db.add(e)
    db.flush()
    audit(db, "website", "enquiry.received", "enquiry", e.id, after={"service": e.service})
    lines = [f"From: {e.name}", f"Email: {e.email or '-'}", f"Phone: {e.phone or '-'}"]
    if e.organisation:
        lines.append(f"Organisation: {e.organisation}")
    if e.service:
        lines.append(f"Service: {e.service}")
    notify_admin(f"New website enquiry: {e.name}", "\n".join([*lines, "", e.message]), kind="enquiries", db=db, link="/enquiries")
    db.commit()
    return _cors(request, JSONResponse({"ok": True}, status_code=201))


@router.get("/api/enquiries", response_model=list[EnquiryOut])
def list_enquiries(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.scalars(select(Enquiry).order_by(Enquiry.created_at.desc(), Enquiry.id.desc()).limit(500))
    return [EnquiryOut.of(e) for e in rows]


def _get(db: Session, enquiry_id: int) -> Enquiry:
    e = db.get(Enquiry, enquiry_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enquiry not found")
    return e


@router.patch("/api/enquiries/{enquiry_id}", response_model=EnquiryOut)
def update_enquiry(enquiry_id: int, body: EnquiryUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    e = _get(db, enquiry_id)
    if body.status == "converted" and not e.client_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use 'Make client' to convert an enquiry")
    before = e.status
    e.status = body.status
    audit(db, admin.email, "enquiry.status", "enquiry", e.id, before={"status": before}, after={"status": e.status})
    db.commit()
    return EnquiryOut.of(e)


@router.post("/api/enquiries/{enquiry_id}/client", response_model=EnquiryOut)
def make_client(enquiry_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Create a client from the enquiry (once). The founder completes the details on the client's page."""
    e = _get(db, enquiry_id)
    if e.client_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This enquiry is already a client")
    c = Client(
        name=e.organisation or e.name,
        contact_name=e.name if e.organisation else None,
        email=e.email,
        phone=e.phone,
        kind="company" if e.organisation else "individual",
    )
    db.add(c)
    db.flush()
    e.client_id = c.id
    e.status = "converted"
    audit(db, admin.email, "enquiry.converted", "enquiry", e.id, after={"client_id": c.id})
    db.commit()
    return EnquiryOut.of(e)
