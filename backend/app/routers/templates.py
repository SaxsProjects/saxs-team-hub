"""The company template library: official letterheads, offer letters, contracts and policies, kept in one place.

Founder only. Templates are PDFs. Uploading a new file adds a version and keeps the earlier ones, so what was
used before can always be found again. Templates are archived, never deleted. Every change is audited.
"""

import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import CompanyTemplate, CompanyTemplateVersion, User
from ..services import audit, store_document
from .people import read_pdf_upload

router = APIRouter(prefix="/api", tags=["templates"])

Category = Literal["letterhead", "offer", "contract", "policy", "finance", "other"]


class TemplateVersionOut(BaseModel):
    version: int
    filename: str
    size: int
    sha256: str
    note: str | None
    uploaded_by: str
    created_at: datetime


class TemplateOut(BaseModel):
    id: int
    name: str
    category: str
    description: str | None
    archived: bool
    updated_at: datetime
    updated_by: str
    current: TemplateVersionOut
    versions: list[TemplateVersionOut]


class TemplateEdit(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: Category
    description: str | None = Field(None, max_length=1000)


def _version_out(v: CompanyTemplateVersion) -> TemplateVersionOut:
    d = v.document
    return TemplateVersionOut(
        version=v.version,
        filename=d.filename,
        size=d.size,
        sha256=d.sha256,
        note=v.note,
        uploaded_by=v.uploaded_by,
        created_at=v.created_at,
    )


def template_out(t: CompanyTemplate) -> TemplateOut:
    versions = [_version_out(v) for v in t.versions]
    return TemplateOut(
        id=t.id,
        name=t.name,
        category=t.category,
        description=t.description,
        archived=t.archived_at is not None,
        updated_at=t.updated_at,
        updated_by=t.updated_by,
        current=versions[0],
        versions=versions,
    )


def _get(db: Session, template_id: int) -> CompanyTemplate:
    t = db.get(CompanyTemplate, template_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return t


def _clean(text: str | None, limit: int) -> str | None:
    text = (text or "").strip()
    return text[:limit] or None


def _name_taken(db: Session, name: str, except_id: int | None = None) -> bool:
    q = select(CompanyTemplate.id).where(func.lower(CompanyTemplate.name) == name.lower())
    if except_id is not None:
        q = q.where(CompanyTemplate.id != except_id)
    return db.scalar(q) is not None


def _add_version(
    db: Session, t: CompanyTemplate, file: UploadFile, data: bytes, note: str | None, actor: str
) -> CompanyTemplateVersion:
    number = (
        db.scalar(select(func.max(CompanyTemplateVersion.version)).where(CompanyTemplateVersion.template_id == t.id)) or 0
    ) + 1
    doc = store_document(
        db,
        person_id=None,
        kind="company_template",
        filename=(file.filename or f"{t.name}.pdf"),
        content_type="application/pdf",
        content=data,
    )
    v = CompanyTemplateVersion(template_id=t.id, version=number, document_id=doc.id, note=note, uploaded_by=actor)
    db.add(v)
    t.updated_by = actor
    t.updated_at = datetime.now(UTC)
    db.flush()
    db.refresh(t)
    return v


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(include_archived: bool = False, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    q = select(CompanyTemplate).order_by(CompanyTemplate.category, func.lower(CompanyTemplate.name))
    if not include_archived:
        q = q.where(CompanyTemplate.archived_at.is_(None))
    return [template_out(t) for t in db.scalars(q).all()]


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(
    name: str = Form(..., min_length=2, max_length=120),
    category: Category = Form(...),
    description: str | None = Form(None, max_length=1000),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    name = name.strip()
    if len(name) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give the template a name")
    if _name_taken(db, name):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A template with this name already exists; upload a new version of it instead"
        )
    data = await read_pdf_upload(file)
    t = CompanyTemplate(name=name, category=category, description=_clean(description, 1000), updated_by=admin.email)
    db.add(t)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A template with this name already exists") from exc
    v = _add_version(db, t, file, data, None, admin.email)
    audit(
        db,
        admin.email,
        "template.create",
        "company_template",
        t.id,
        after={"name": name, "category": category, "sha256": v.document.sha256},
    )
    db.commit()
    return template_out(t)


@router.post("/templates/{template_id}/versions", response_model=TemplateOut, status_code=201)
async def upload_version(
    template_id: int,
    note: str | None = Form(None, max_length=300),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    t = _get(db, template_id)
    if t.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Restore the template before uploading a new version")
    data = await read_pdf_upload(file)
    v = _add_version(db, t, file, data, _clean(note, 300), admin.email)
    audit(
        db,
        admin.email,
        "template.new_version",
        "company_template",
        t.id,
        after={"version": v.version, "sha256": v.document.sha256},
    )
    db.commit()
    return template_out(t)


@router.put("/templates/{template_id}", response_model=TemplateOut)
def edit_template(template_id: int, body: TemplateEdit, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    t = _get(db, template_id)
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give the template a name")
    if _name_taken(db, name, except_id=t.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A template with this name already exists")
    before = {"name": t.name, "category": t.category, "description": t.description}
    t.name, t.category, t.description = name, body.category, _clean(body.description, 1000)
    t.updated_by = admin.email
    audit(
        db,
        admin.email,
        "template.edit",
        "company_template",
        t.id,
        before=before,
        after={"name": t.name, "category": t.category, "description": t.description},
    )
    db.commit()
    return template_out(t)


@router.post("/templates/{template_id}/archive", response_model=TemplateOut)
def archive_template(template_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    t = _get(db, template_id)
    if t.archived_at is None:
        t.archived_at = datetime.now(UTC)
        t.updated_by = admin.email
        audit(db, admin.email, "template.archive", "company_template", t.id)
        db.commit()
    return template_out(t)


@router.post("/templates/{template_id}/restore", response_model=TemplateOut)
def restore_template(template_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    t = _get(db, template_id)
    if _name_taken(db, t.name, except_id=t.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Another template now has this name; rename one of them first")
    if t.archived_at is not None:
        t.archived_at = None
        t.updated_by = admin.email
        audit(db, admin.email, "template.restore", "company_template", t.id)
        db.commit()
    return template_out(t)


def _download_name(t: CompanyTemplate, version: int) -> str:
    base = re.sub(r"[^A-Za-z0-9 ._-]", "", t.name).strip().replace(" ", "_") or "template"
    return f"{base[:80]}_v{version}.pdf"


@router.get("/templates/{template_id}/pdf")
def template_pdf(template_id: int, version: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    t = _get(db, template_id)
    v = t.versions[0] if version is None else next((v for v in t.versions if v.version == version), None)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return Response(
        v.document.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{_download_name(t, v.version)}"'},
    )
