"""Statements of account for clients and the monthly finance report."""

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..client_finance import finance_report, issue_statement, report_pdf, statement_preview
from ..db import get_db
from ..deps import require_admin
from ..models import Document, User
from ..services import today_local
from .finance import get_client

router = APIRouter(prefix="/api", tags=["reports"])

PDF_TYPE = "application/pdf"
MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _pdf(content: bytes, filename: str) -> Response:
    return Response(content, media_type=PDF_TYPE, headers={"Content-Disposition": f'inline; filename="{filename}"'})


def _month(value: str | None) -> date:
    if not value:
        return today_local().replace(day=1)
    match = MONTH.match(value)
    if not match:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must look like 2026-11")
    month = date(int(match[1]), int(match[2]), 1)
    if month > today_local():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That month has not started yet")
    return month


class StatementIn(BaseModel):
    email: bool = False


class StatementOut(BaseModel):
    number: str
    document_id: int
    emailed: bool


@router.get("/clients/{client_id}/statement.pdf")
def preview_statement(client_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    client = get_client(db, client_id)
    return _pdf(statement_preview(db, client), "statement-preview.pdf")


@router.post("/clients/{client_id}/statements", response_model=StatementOut, status_code=201)
def create_statement(client_id: int, body: StatementIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    client = get_client(db, client_id)
    try:
        stored, number, emailed = issue_statement(db, client, actor=admin.email, email=body.email)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return StatementOut(number=number, document_id=stored.id, emailed=emailed)


@router.get("/statements/{document_id}.pdf")
def statement_file(document_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    doc = db.get(Document, document_id)
    if not doc or doc.kind != "statement":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
    return _pdf(doc.content, doc.filename)


@router.get("/reports/finance")
def finance_report_json(month: str | None = Query(None), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return finance_report(db, _month(month))


@router.get("/reports/finance.pdf")
def finance_report_file(month: str | None = Query(None), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    period = _month(month)
    return _pdf(report_pdf(db, period), f"SaxsProjects_Finance_Report_{period:%Y-%m}.pdf")
