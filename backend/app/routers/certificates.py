"""Certificates (SP-CERT) for anything the company certifies: completion, training, service, partnership and more.

Issued certificates are stored once (with their SHA-256) and can be revoked, never edited. Anyone holding one
can check it at /verify/<code> (see pages.py); the check shows only what is printed on the certificate.
"""

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..certificates import PRESETS, certificate_pdf, new_verify_code, preset
from ..company import company_settings
from ..db import get_db
from ..deps import require_admin
from ..models import Certificate, Document, User
from ..numbering import allocate_number
from ..schemas import ORM
from ..services import audit, link, store_document, today_local
from .finance import _require, readiness

router = APIRouter(prefix="/api/certificates", tags=["certificates"])

PDF_TYPE = "application/pdf"
Kind = Literal[
    "completion",
    "achievement",
    "appreciation",
    "participation",
    "recognition",
    "training",
    "service",
    "project",
    "partnership",
    "custom",
]


class CertificateIn(BaseModel):
    kind: Kind = "completion"
    recipient_name: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=3, max_length=400)
    title: str | None = Field(default=None, min_length=2, max_length=40)
    subtitle: str | None = Field(default=None, max_length=40)
    lead: str | None = Field(default=None, min_length=2, max_length=120)
    issue_date: date | None = None
    place: str | None = Field(default=None, min_length=2, max_length=120)


class RevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class CertificateOut(ORM):
    id: int
    number: str
    kind: str
    title: str
    subtitle: str | None
    lead: str
    recipient_name: str
    body: str
    issue_date: date
    place: str
    verify_code: str
    revoked_at: datetime | None
    revoke_reason: str | None
    pdf_sha256: str
    created_at: datetime
    verify_url: str = ""


def _out(cert: Certificate) -> CertificateOut:
    out = CertificateOut.model_validate(cert)
    out.verify_url = verify_url(cert.verify_code)
    return out


def verify_url(code: str) -> str:
    return link(f"/verify/{code}")


def get_certificate(db: Session, certificate_id: int) -> Certificate:
    cert = db.get(Certificate, certificate_id)
    if not cert:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    return cert


@router.get("/presets")
def presets(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    s = company_settings(db)
    return [preset(kind, s) for kind in PRESETS]


@router.get("", response_model=list[CertificateOut])
def list_certificates(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [_out(c) for c in db.scalars(select(Certificate).order_by(Certificate.id.desc()))]


@router.post("/preview")
def preview_certificate(body: CertificateIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """What the certificate will look like: unsigned, numbered SP-CERT-PREVIEW, nothing is saved."""
    cert = _build(db, body, number="SP-CERT-PREVIEW", code="preview")
    content = certificate_pdf(cert, verify_url=None, signed=False, company=company_settings(db))
    return Response(content, media_type=PDF_TYPE, headers={"Content-Disposition": 'inline; filename="certificate-preview.pdf"'})


def _build(db: Session, body: CertificateIn, *, number: str, code: str) -> Certificate:
    s = company_settings(db)
    base = preset(body.kind, s)
    issue_date = body.issue_date or today_local()
    if issue_date > today_local():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A certificate cannot be dated in the future")
    return Certificate(
        number=number,
        kind=body.kind,
        title=(body.title or base["title"]).strip().upper(),
        subtitle=(body.subtitle if body.subtitle is not None else base["subtitle"]).strip().upper() or None,
        lead=(body.lead or base["lead"]).strip(),
        recipient_name=body.recipient_name.strip(),
        body=body.body.strip(),
        issue_date=issue_date,
        place=(body.place or s.certificate_place).strip(),
        verify_code=code,
    )


@router.post("", response_model=CertificateOut, status_code=201)
def issue_certificate(body: CertificateIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if "____" in body.body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fill in the blanks in the certificate text first")
    _require(db, readiness(db).can_issue_quotations, "certificates are signed")
    cert = _build(db, body, number=allocate_number(db, "CERT"), code=new_verify_code())
    content = certificate_pdf(cert, verify_url=verify_url(cert.verify_code), signed=True, company=company_settings(db))
    stored = store_document(
        db, person_id=None, kind="certificate", filename=f"{cert.number}.pdf", content_type=PDF_TYPE, content=content
    )
    cert.pdf_document_id = stored.id
    cert.pdf_sha256 = stored.sha256
    cert.issued_by = admin.email
    db.add(cert)
    db.flush()
    audit(db, admin.email, "certificate.issue", "certificate", cert.id, after={"number": cert.number, "kind": cert.kind})
    db.commit()
    return _out(cert)


@router.get("/{certificate_id}/pdf")
def certificate_file(certificate_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cert = get_certificate(db, certificate_id)
    doc = db.get(Document, cert.pdf_document_id)
    return Response(doc.content, media_type=PDF_TYPE, headers={"Content-Disposition": f'inline; filename="{cert.number}.pdf"'})


@router.post("/{certificate_id}/revoke", response_model=CertificateOut)
def revoke_certificate(certificate_id: int, body: RevokeIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cert = get_certificate(db, certificate_id)
    if cert.revoked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already revoked")
    cert.revoked_at = datetime.now(UTC)
    cert.revoke_reason = body.reason.strip()
    audit(db, admin.email, "certificate.revoke", "certificate", cert.id, after={"reason": cert.revoke_reason})
    db.commit()
    return _out(cert)


def find_by_code(db: Session, code: str) -> Certificate | None:
    if not code or len(code) > 32:
        return None
    return db.scalar(select(Certificate).where(Certificate.verify_code == code))
