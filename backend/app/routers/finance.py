"""Clients, quotations, invoices, receipts and credit notes (founder plan tasks 14 and 15).

Rules:
- Drafts can be edited; they have no number and their PDF carries a DRAFT watermark and no signature.
- Issuing assigns the next gapless number, renders the PDF once, stores it with its SHA-256 and locks
  the document. Issued documents are never edited or deleted: an invoice is corrected with a credit note.
- Quotations and receipts carry the director's signature, so issuing needs the signature configured.
  Invoices also need the company registration number and banking details.
- A payment on an invoice issues a signed receipt and, if the invoice belongs to a project, records the
  client payment (excluding VAT) that drives contributor payouts.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..company import company_settings
from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..finance import MAX_CENTS, document_totals, excluding_vat, line_total, portion_of
from ..models import Client, CreditNote, Document, Invoice, LineItem, Project, Quotation, Receipt, User
from ..numbering import allocate_number
from ..pdf import credit_note_pdf, invoice_pdf, quotation_pdf, receipt_pdf
from ..schemas_finance import (
    ClientIn,
    ClientOut,
    ClientUpdate,
    CreditNoteIn,
    CreditNoteOut,
    CreditNoteRecordedOut,
    FinanceReadinessOut,
    InvoiceIn,
    InvoiceOut,
    InvoicePaymentIn,
    InvoicePaymentOut,
    InvoiceUpdate,
    LineIn,
    QuotationIn,
    QuotationOut,
    QuotationUpdate,
    ReceiptOut,
)
from ..services import audit, store_document, today_local

router = APIRouter(prefix="/api", tags=["finance"])

PDF_TYPE = "application/pdf"


# ---- Helpers ---------------------------------------------------------------------------------------


def readiness(db: Session) -> FinanceReadinessOut:
    s = company_settings(db)
    missing = []
    if not s.signature_configured:
        missing.append("SIGNATURE_IMAGE_PATH or SIGNATURE_IMAGE_BASE64")
    if not s.signatory_name.strip():
        missing.append("SIGNATORY_NAME")
    can_quote = not missing
    if not s.company_registration_number.strip():
        missing.append("COMPANY_REGISTRATION_NUMBER")
    if not s.bank_configured:
        missing.append("COMPANY_BANK_NAME, COMPANY_BANK_ACCOUNT_NUMBER and COMPANY_BANK_BRANCH_CODE")
    return FinanceReadinessOut(
        registration_number_set=bool(s.company_registration_number.strip()),
        bank_details_set=s.bank_configured,
        signature_set=s.signature_configured,
        signatory_name_set=bool(s.signatory_name.strip()),
        vat_registered=s.vat_registered,
        can_issue_quotations=can_quote,
        can_issue_invoices=not missing,
        missing=missing,
    )


def _require(db: Session, ok: bool, what: str) -> None:
    if not ok:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot issue yet: set {', '.join(readiness(db).missing)} first ({what})")


def _vat_rate(db: Session) -> int:
    s = company_settings(db)
    return s.vat_rate_bp if s.vat_registered else 0


def get_client(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    return client


def _check_project(db: Session, project_id: int | None) -> None:
    if project_id is not None and not db.get(Project, project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")


def _set_lines(db: Session, doc: Quotation | Invoice, lines: list[LineIn]) -> None:
    doc.lines.clear()
    for position, line in enumerate(lines, start=1):
        amount = line_total(line.quantity, line.unit_price_cents)
        if amount > MAX_CENTS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A line total is too large")
        doc.lines.append(
            LineItem(
                position=position,
                description=line.description.strip(),
                quantity=line.quantity,
                unit_price_cents=line.unit_price_cents,
                line_total_cents=amount,
            )
        )
    _recalculate(db, doc)


def _recalculate(db: Session, doc: Quotation | Invoice) -> None:
    try:
        totals = document_totals([line.line_total_cents for line in doc.lines], _vat_rate(db))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    doc.vat_rate_bp = _vat_rate(db)
    doc.subtotal_cents = totals.subtotal_cents
    doc.vat_cents = totals.vat_cents
    doc.total_cents = totals.total_cents


def _stored_pdf(db: Session, document_id: int | None, filename: str) -> Response:
    doc = db.get(Document, document_id) if document_id else None
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return _pdf_response(doc.content, filename)


def _pdf_response(content: bytes, filename: str) -> Response:
    return Response(content, media_type=PDF_TYPE, headers={"Content-Disposition": f'inline; filename="{filename}"'})


def _store_pdf(db: Session, kind: str, number: str, content: bytes) -> Document:
    return store_document(db, person_id=None, kind=kind, filename=f"{number}.pdf", content_type=PDF_TYPE, content=content)


def invoice_out(inv: Invoice) -> InvoiceOut:
    out = InvoiceOut.model_validate(inv)
    out.overdue = bool(
        inv.status in ("issued", "part_paid") and inv.due_date and inv.due_date < today_local() and inv.balance_cents > 0
    )
    return out


def _refresh_invoice_status(inv: Invoice) -> None:
    if inv.balance_cents == 0:
        inv.status = "paid" if inv.paid_cents > 0 else "void"
    elif inv.paid_cents > 0:
        inv.status = "part_paid"
    else:
        inv.status = "issued"


# ---- Readiness -----------------------------------------------------------------------------------


@router.get("/finance/readiness", response_model=FinanceReadinessOut)
def finance_readiness(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Which company settings are still missing before quotations and invoices can be issued."""
    return readiness(db)


# ---- Clients -------------------------------------------------------------------------------------


@router.get("/clients", response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(Client).order_by(Client.name)).all()


def _clean_client_fields(values: dict) -> dict:
    """Blank optional fields are stored as empty (NULL), never as spaces; required flags are never set to null."""
    for key in ("kind", "reminders_enabled"):
        if key in values and values[key] is None:
            values.pop(key)
    for key in ("registration_number", "vat_number", "contact_name", "phone", "address"):
        if isinstance(values.get(key), str):
            values[key] = values[key].strip() or None
    return values


@router.post("/clients", response_model=ClientOut, status_code=201)
def create_client(body: ClientIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    client = Client(**_clean_client_fields(body.model_dump()))
    db.add(client)
    db.flush()
    audit(db, admin.email, "client.create", "client", client.id)
    db.commit()
    return client


@router.get("/clients/{client_id}", response_model=ClientOut)
def read_client(client_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return get_client(db, client_id)


@router.patch("/clients/{client_id}", response_model=ClientOut)
def update_client(client_id: int, body: ClientUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    client = get_client(db, client_id)
    changes = _clean_client_fields(body.model_dump(exclude_unset=True))
    if "name" in changes and not changes["name"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "name cannot be empty")
    for key, value in changes.items():
        setattr(client, key, value)
    audit(db, admin.email, "client.update", "client", client.id, after={"fields": sorted(changes)})
    db.commit()
    return client


# ---- Quotations ----------------------------------------------------------------------------------


def get_quotation(db: Session, quotation_id: int) -> Quotation:
    q = db.get(Quotation, quotation_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation not found")
    return q


def _expire_if_past(db: Session, q: Quotation, actor: str) -> bool:
    if q.status == "issued" and q.valid_until and q.valid_until < today_local():
        q.status = "expired"
        audit(db, actor, "quotation.expire", "quotation", q.id)
        return True
    return False


@router.get("/quotations", response_model=list[QuotationOut])
def list_quotations(status_filter: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    stmt = select(Quotation).order_by(Quotation.created_at.desc())
    if status_filter:
        stmt = stmt.where(Quotation.status == status_filter)
    return db.scalars(stmt).all()


@router.post("/quotations", response_model=QuotationOut, status_code=201)
def create_quotation(body: QuotationIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    get_client(db, body.client_id)
    _check_project(db, body.project_id)
    q = Quotation(client_id=body.client_id, project_id=body.project_id, title=body.title.strip(), notes=body.notes)
    db.add(q)
    _set_lines(db, q, body.lines)
    db.flush()
    audit(db, admin.email, "quotation.create", "quotation", q.id, after={"total_cents": q.total_cents})
    db.commit()
    return q


@router.get("/quotations/{quotation_id}", response_model=QuotationOut)
def read_quotation(quotation_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return get_quotation(db, quotation_id)


@router.patch("/quotations/{quotation_id}", response_model=QuotationOut)
def update_quotation(
    quotation_id: int, body: QuotationUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    q = get_quotation(db, quotation_id)
    if q.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "An issued quotation cannot be changed")
    changes = body.model_dump(exclude_unset=True)
    if "project_id" in changes:
        _check_project(db, changes["project_id"])
        q.project_id = changes["project_id"]
    if changes.get("title"):
        q.title = changes["title"].strip()
    if "notes" in changes:
        q.notes = changes["notes"]
    if body.lines is not None:
        _set_lines(db, q, body.lines)
    audit(db, admin.email, "quotation.update", "quotation", q.id, after={"total_cents": q.total_cents})
    db.commit()
    return q


@router.delete("/quotations/{quotation_id}", status_code=204)
def delete_draft_quotation(quotation_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    q = get_quotation(db, quotation_id)
    if q.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only drafts can be deleted; issued quotations are kept")
    db.delete(q)
    audit(db, admin.email, "quotation.delete_draft", "quotation", quotation_id)
    db.commit()


@router.post("/quotations/{quotation_id}/issue", response_model=QuotationOut)
def issue_quotation(quotation_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    q = get_quotation(db, quotation_id)
    if q.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "This quotation has already been issued")
    if not q.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add at least one line first")
    _require(db, readiness(db).can_issue_quotations, "quotations are signed")
    _recalculate(db, q)
    today = today_local()
    q.issue_date = today
    q.valid_until = today + timedelta(days=get_settings().quote_valid_days)
    q.number = allocate_number(db, "Q")
    q.status = "issued"
    q.issued_at = datetime.now(UTC)
    stored = _store_pdf(db, "quotation", q.number, quotation_pdf(q, draft=False, company=company_settings(db)))
    q.pdf_document_id = stored.id
    q.pdf_sha256 = stored.sha256
    audit(
        db,
        admin.email,
        "quotation.issue",
        "quotation",
        q.id,
        after={"number": q.number, "total_cents": q.total_cents, "sha256": stored.sha256},
    )
    db.commit()
    return q


@router.post("/quotations/{quotation_id}/accept", response_model=QuotationOut)
def accept_quotation(quotation_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Record that the client accepted. Creates the project if the quotation has none yet."""
    q = get_quotation(db, quotation_id)
    if _expire_if_past(db, q, admin.email):
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "This quotation has expired; issue a new one")
    if q.status != "issued":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only an issued quotation can be accepted (it is {q.status})")
    q.status = "accepted"
    q.responded_at = datetime.now(UTC)
    if q.project_id is None:
        project = Project(
            name=q.title, client_name=q.client.name, client_id=q.client_id, description=f"From quotation {q.number}"
        )
        db.add(project)
        db.flush()
        q.project_id = project.id
        audit(db, admin.email, "project.create", "project", project.id, after={"from_quotation": q.number})
    audit(db, admin.email, "quotation.accept", "quotation", q.id, after={"project_id": q.project_id})
    db.commit()
    return q


@router.post("/quotations/{quotation_id}/decline", response_model=QuotationOut)
def decline_quotation(quotation_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    q = get_quotation(db, quotation_id)
    if q.status != "issued":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only an issued quotation can be declined (it is {q.status})")
    q.status = "declined"
    q.responded_at = datetime.now(UTC)
    audit(db, admin.email, "quotation.decline", "quotation", q.id)
    db.commit()
    return q


@router.get("/quotations/{quotation_id}/pdf")
def quotation_pdf_file(quotation_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """The issued, signed PDF exactly as stored, or a watermarked, unsigned preview of a draft."""
    q = get_quotation(db, quotation_id)
    if q.pdf_document_id:
        return _stored_pdf(db, q.pdf_document_id, f"{q.number}.pdf")
    return _pdf_response(quotation_pdf(q, draft=True, company=company_settings(db)), f"quotation-draft-{q.id}.pdf")


# ---- Invoices ------------------------------------------------------------------------------------


def get_invoice(db: Session, invoice_id: int) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return inv


def _already_invoiced(db: Session, quotation_id: int) -> int:
    """Subtotal (excluding VAT) already billed on a quotation, net of credit notes."""
    rows = db.scalars(select(Invoice).where(Invoice.quotation_id == quotation_id, Invoice.status != "void")).all()
    billed = 0
    for inv in rows:
        credited_ex_vat = excluding_vat(inv.credited_cents, inv.subtotal_cents, inv.total_cents)
        billed += inv.subtotal_cents - credited_ex_vat
    return billed


@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(unpaid: bool = False, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    stmt = select(Invoice).order_by(Invoice.created_at.desc())
    if unpaid:
        stmt = stmt.where(Invoice.status.in_(("issued", "part_paid")))
    return [invoice_out(inv) for inv in db.scalars(stmt)]


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(body: InvoiceIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.quotation_id is not None:
        q = get_quotation(db, body.quotation_id)
        if q.status != "accepted":
            raise HTTPException(status.HTTP_409_CONFLICT, "Only an accepted quotation can be turned into an invoice")
        remaining = q.subtotal_cents - _already_invoiced(db, q.id)
        if remaining <= 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "This quotation has been invoiced in full")
        inv = Invoice(
            client_id=q.client_id,
            project_id=q.project_id,
            quotation_id=q.id,
            title=(body.title or q.title).strip(),
            notes=body.notes,
        )
        db.add(inv)
        if body.portion_percent is None and remaining == q.subtotal_cents:
            lines = [
                LineIn(description=line.description, quantity=line.quantity, unit_price_cents=line.unit_price_cents)
                for line in q.lines
            ]
        else:
            if body.portion_percent is not None:
                amount = portion_of(q.subtotal_cents, body.portion_percent)
                if amount > remaining:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT, f"Only {remaining / 100:.2f} (excl. VAT) is left to invoice on {q.number}"
                    )
                kind = "deposit" if body.portion_percent < 100 else "payment"
                label = f"{body.portion_percent}% {kind} for quotation {q.number}: {q.title}"
            else:
                amount = remaining
                label = f"Balance for quotation {q.number}: {q.title}"
            lines = [LineIn(description=label[:500], quantity=1, unit_price_cents=amount)]
        _set_lines(db, inv, lines)
    else:
        if body.client_id is None or not body.title or not body.lines:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give a quotation_id, or a client_id, title and lines")
        if body.portion_percent is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "portion_percent only applies to invoices from a quotation")
        get_client(db, body.client_id)
        _check_project(db, body.project_id)
        inv = Invoice(client_id=body.client_id, project_id=body.project_id, title=body.title.strip(), notes=body.notes)
        db.add(inv)
        _set_lines(db, inv, body.lines)
    db.flush()
    audit(
        db,
        admin.email,
        "invoice.create",
        "invoice",
        inv.id,
        after={"total_cents": inv.total_cents, "quotation_id": inv.quotation_id},
    )
    db.commit()
    return invoice_out(inv)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def read_invoice(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return invoice_out(get_invoice(db, invoice_id))


@router.patch("/invoices/{invoice_id}", response_model=InvoiceOut)
def update_invoice(invoice_id: int, body: InvoiceUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    inv = get_invoice(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "An issued invoice cannot be changed; issue a credit note instead")
    changes = body.model_dump(exclude_unset=True)
    if "project_id" in changes:
        _check_project(db, changes["project_id"])
        inv.project_id = changes["project_id"]
    if changes.get("title"):
        inv.title = changes["title"].strip()
    if "notes" in changes:
        inv.notes = changes["notes"]
    if body.lines is not None:
        if inv.quotation_id is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Lines of an invoice made from a quotation come from that quotation")
        _set_lines(db, inv, body.lines)
    audit(db, admin.email, "invoice.update", "invoice", inv.id, after={"total_cents": inv.total_cents})
    db.commit()
    return invoice_out(inv)


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete_draft_invoice(invoice_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    inv = get_invoice(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only drafts can be deleted; issued invoices are kept")
    db.delete(inv)
    audit(db, admin.email, "invoice.delete_draft", "invoice", invoice_id)
    db.commit()


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceOut)
def issue_invoice(invoice_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    inv = get_invoice(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "This invoice has already been issued")
    if not inv.lines or inv.total_cents <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An invoice needs at least one line and a total above zero")
    _require(db, readiness(db).can_issue_invoices, "invoices need the registration number, banking details and signature")
    _recalculate(db, inv)
    today = today_local()
    inv.issue_date = today
    inv.due_date = today + timedelta(days=get_settings().invoice_due_days)
    inv.number = allocate_number(db, "INV")
    inv.status = "issued"
    inv.issued_at = datetime.now(UTC)
    stored = _store_pdf(db, "invoice", inv.number, invoice_pdf(inv, draft=False, company=company_settings(db)))
    inv.pdf_document_id = stored.id
    inv.pdf_sha256 = stored.sha256
    audit(
        db,
        admin.email,
        "invoice.issue",
        "invoice",
        inv.id,
        after={"number": inv.number, "total_cents": inv.total_cents, "sha256": stored.sha256},
    )
    db.commit()
    return invoice_out(inv)


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf_file(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """The issued PDF exactly as stored, or a watermarked preview of a draft."""
    inv = get_invoice(db, invoice_id)
    if inv.pdf_document_id:
        return _stored_pdf(db, inv.pdf_document_id, f"{inv.number}.pdf")
    return _pdf_response(invoice_pdf(inv, draft=True, company=company_settings(db)), f"invoice-draft-{inv.id}.pdf")


def _check_payment(inv: Invoice, body: InvoicePaymentIn) -> None:
    if inv.status not in ("issued", "part_paid"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Payments can only be recorded on an issued, unpaid invoice (it is {inv.status})"
        )
    if body.amount_cents > inv.balance_cents:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"The amount is more than the balance due ({inv.balance_cents / 100:.2f})"
        )
    if body.received_on > today_local():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The payment date cannot be in the future")


def _check_credit(inv: Invoice, body: CreditNoteIn) -> None:
    if inv.status not in ("issued", "part_paid"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Credit notes apply to issued, unpaid invoices (it is {inv.status})")
    if body.amount_cents > inv.balance_cents:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"The credit is more than the balance due ({inv.balance_cents / 100:.2f})"
        )


def _invoice_after(inv: Invoice, less_cents: int) -> SimpleNamespace:
    """A read-only stand-in for the invoice as it will look once this payment or credit is applied.
    Plain attributes (not a model instance), so a preview can never be flushed into the database."""
    return SimpleNamespace(
        number=inv.number,
        title=inv.title,
        issue_date=inv.issue_date,
        client=inv.client,
        total_cents=inv.total_cents,
        credited_cents=inv.credited_cents,
        balance_cents=inv.balance_cents - less_cents,
    )


@router.post("/invoices/{invoice_id}/payments/preview")
def preview_invoice_payment(
    invoice_id: int, body: InvoicePaymentIn, db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    """The receipt this payment would issue, watermarked and unsigned. Nothing is saved."""
    inv = get_invoice(db, invoice_id)
    _check_payment(inv, body)
    receipt = SimpleNamespace(
        number="(numbered when issued)",
        issue_date=today_local(),
        amount_cents=body.amount_cents,
        received_on=body.received_on,
        method=body.method,
        reference=body.reference.strip(),
    )
    pdf = receipt_pdf(receipt, _invoice_after(inv, body.amount_cents), company=company_settings(db), preview=True)
    return _pdf_response(pdf, f"receipt-preview-{inv.number}.pdf")


@router.post("/invoices/{invoice_id}/credit-notes/preview")
def preview_credit_note(invoice_id: int, body: CreditNoteIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """The credit note this would issue, watermarked and unsigned. Nothing is saved."""
    inv = get_invoice(db, invoice_id)
    _check_credit(inv, body)
    note = SimpleNamespace(
        number="(numbered when issued)", issue_date=today_local(), amount_cents=body.amount_cents, reason=body.reason.strip()
    )
    pdf = credit_note_pdf(note, _invoice_after(inv, body.amount_cents), company=company_settings(db), preview=True)
    return _pdf_response(pdf, f"credit-note-preview-{inv.number}.pdf")


@router.post("/invoices/{invoice_id}/payments", response_model=InvoicePaymentOut, status_code=201)
def record_invoice_payment(
    invoice_id: int, body: InvoicePaymentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    """Record money received against an invoice: issues a signed receipt and triggers contributor payouts."""
    from ..terms import release_deferred_fees
    from .projects import record_client_payment

    inv = get_invoice(db, invoice_id)
    _check_payment(inv, body)
    _require(db, readiness(db).can_issue_quotations, "receipts are signed")

    payouts = []
    client_payment_id = None
    reference = body.reference.strip()
    if inv.project_id is not None:
        project = db.get(Project, inv.project_id)
        payment, payouts = record_client_payment(
            db,
            project,
            amount_cents=excluding_vat(body.amount_cents, inv.subtotal_cents, inv.total_cents),
            received_at=body.received_on,
            reference=f"{inv.number} / {reference}"[:120],
            actor=admin.email,
        )
        client_payment_id = payment.id

    inv.paid_cents += body.amount_cents
    _refresh_invoice_status(inv)
    today = today_local()
    receipt = Receipt(
        number=allocate_number(db, "R"),
        invoice_id=inv.id,
        client_payment_id=client_payment_id,
        amount_cents=body.amount_cents,
        received_on=body.received_on,
        method=body.method,
        reference=reference,
        issue_date=today,
    )
    stored = _store_pdf(db, "receipt", receipt.number, receipt_pdf(receipt, inv, company=company_settings(db)))
    receipt.pdf_document_id = stored.id
    receipt.pdf_sha256 = stored.sha256
    db.add(receipt)
    db.flush()
    release_deferred_fees(db, admin.email)  # an invoice paid without a project is still client income
    audit(
        db,
        admin.email,
        "invoice.payment",
        "receipt",
        receipt.id,
        after={"invoice": inv.number, "amount_cents": body.amount_cents, "receipt": receipt.number, "payouts": len(payouts)},
    )
    db.commit()
    return InvoicePaymentOut(invoice=invoice_out(inv), receipt=receipt, payouts=payouts)


@router.post("/invoices/{invoice_id}/credit-notes", response_model=CreditNoteRecordedOut, status_code=201)
def issue_credit_note(invoice_id: int, body: CreditNoteIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Reduce what the client owes on an issued invoice (the invoice itself is never edited)."""
    inv = get_invoice(db, invoice_id)
    _check_credit(inv, body)
    _require(db, readiness(db).can_issue_quotations, "credit notes are signed")
    inv.credited_cents += body.amount_cents
    _refresh_invoice_status(inv)
    today = today_local()
    note = CreditNote(
        number=allocate_number(db, "CN"),
        invoice_id=inv.id,
        reason=body.reason.strip(),
        amount_cents=body.amount_cents,
        issue_date=today,
    )
    stored = _store_pdf(db, "credit_note", note.number, credit_note_pdf(note, inv, company=company_settings(db)))
    note.pdf_document_id = stored.id
    note.pdf_sha256 = stored.sha256
    db.add(note)
    db.flush()
    audit(
        db,
        admin.email,
        "invoice.credit_note",
        "credit_note",
        note.id,
        after={"invoice": inv.number, "amount_cents": note.amount_cents},
    )
    db.commit()
    return CreditNoteRecordedOut(invoice=invoice_out(inv), credit_note=note)


@router.get("/invoices/{invoice_id}/receipts", response_model=list[ReceiptOut])
def list_receipts(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return get_invoice(db, invoice_id).receipts


@router.get("/invoices/{invoice_id}/credit-notes", response_model=list[CreditNoteOut])
def list_credit_notes(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return get_invoice(db, invoice_id).credit_notes


@router.get("/receipts/{receipt_id}/pdf")
def receipt_pdf_file(receipt_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    return _stored_pdf(db, receipt.pdf_document_id, f"{receipt.number}.pdf")


@router.get("/credit-notes/{credit_note_id}/pdf")
def credit_note_pdf_file(credit_note_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    note = db.get(CreditNote, credit_note_id)
    if not note:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credit note not found")
    return _stored_pdf(db, note.pdf_document_id, f"{note.number}.pdf")


@router.get("/finance/summary")
def finance_summary(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Totals for the founder's dashboard (all amounts in cents)."""
    open_invoices = db.scalars(select(Invoice).where(Invoice.status.in_(("issued", "part_paid")))).all()
    today = today_local()
    received = db.scalar(select(func.coalesce(func.sum(Receipt.amount_cents), 0))) or 0
    return {
        "invoices_open": len(open_invoices),
        "outstanding_cents": sum(i.balance_cents for i in open_invoices),
        "overdue_cents": sum(i.balance_cents for i in open_invoices if i.due_date and i.due_date < today),
        "received_cents": received,
        "quotations_open": db.scalar(select(func.count(Quotation.id)).where(Quotation.status == "issued")) or 0,
    }
