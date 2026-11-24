"""Request and response shapes for clients, quotations, invoices, receipts and credit notes."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from .schemas import ORM, PayoutOut

Cents = int


class ClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    registration_number: str | None = Field(default=None, max_length=64)
    contact_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=1000)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    registration_number: str | None = Field(default=None, max_length=64)
    contact_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=1000)


class ClientOut(ORM):
    id: int
    name: str
    registration_number: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    created_at: datetime


class LineIn(BaseModel):
    description: str = Field(min_length=2, max_length=500)
    quantity: int = Field(gt=0, le=10_000)
    unit_price_cents: Cents = Field(ge=0, le=2_000_000_000)


class LineOut(ORM):
    id: int
    position: int
    description: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class QuotationIn(BaseModel):
    client_id: int
    project_id: int | None = None
    title: str = Field(min_length=2, max_length=200)
    notes: str | None = Field(default=None, max_length=3000)
    lines: list[LineIn] = Field(default_factory=list, max_length=50)


class QuotationUpdate(BaseModel):
    project_id: int | None = None
    title: str | None = Field(default=None, min_length=2, max_length=200)
    notes: str | None = Field(default=None, max_length=3000)
    lines: list[LineIn] | None = Field(default=None, max_length=50)


class QuotationOut(ORM):
    id: int
    number: str | None
    client_id: int
    project_id: int | None
    title: str
    notes: str | None
    status: str
    issue_date: date | None
    valid_until: date | None
    vat_rate_bp: int
    subtotal_cents: int
    vat_cents: int
    total_cents: int
    pdf_sha256: str | None
    issued_at: datetime | None
    lines: list[LineOut]


class InvoiceIn(BaseModel):
    """Either from an accepted quotation (`quotation_id`), or with a client and lines of its own."""

    quotation_id: int | None = None
    portion_percent: int | None = Field(
        default=None, ge=1, le=100, description="From a quotation: bill this % of it (e.g. 50 for the deposit)"
    )
    client_id: int | None = None
    project_id: int | None = None
    title: str | None = Field(default=None, min_length=2, max_length=200)
    notes: str | None = Field(default=None, max_length=3000)
    lines: list[LineIn] | None = Field(default=None, max_length=50)


class InvoiceUpdate(BaseModel):
    project_id: int | None = None
    title: str | None = Field(default=None, min_length=2, max_length=200)
    notes: str | None = Field(default=None, max_length=3000)
    lines: list[LineIn] | None = Field(default=None, max_length=50)


class InvoiceOut(ORM):
    id: int
    number: str | None
    client_id: int
    project_id: int | None
    quotation_id: int | None
    title: str
    notes: str | None
    status: str
    issue_date: date | None
    due_date: date | None
    vat_rate_bp: int
    subtotal_cents: int
    vat_cents: int
    total_cents: int
    paid_cents: int
    credited_cents: int
    balance_cents: int
    overdue: bool = False
    pdf_sha256: str | None
    issued_at: datetime | None
    lines: list[LineOut]


class InvoicePaymentIn(BaseModel):
    amount_cents: Cents = Field(gt=0, le=2_000_000_000)
    received_on: date
    method: Literal["eft", "cash", "card", "other"] = "eft"
    reference: str = Field(min_length=1, max_length=120)


class ReceiptOut(ORM):
    id: int
    number: str
    invoice_id: int
    amount_cents: int
    received_on: date
    method: str
    reference: str
    issue_date: date
    pdf_sha256: str


class CreditNoteIn(BaseModel):
    amount_cents: Cents = Field(gt=0, le=2_000_000_000)
    reason: str = Field(min_length=3, max_length=500)


class CreditNoteOut(ORM):
    id: int
    number: str
    invoice_id: int
    reason: str
    amount_cents: int
    issue_date: date
    pdf_sha256: str


class InvoicePaymentOut(BaseModel):
    invoice: InvoiceOut
    receipt: ReceiptOut
    payouts: list[PayoutOut]


class CreditNoteRecordedOut(BaseModel):
    invoice: InvoiceOut
    credit_note: CreditNoteOut


class FinanceReadinessOut(BaseModel):
    """What is still missing before real documents can go to clients. Never returns the values themselves."""

    registration_number_set: bool
    bank_details_set: bool
    signature_set: bool
    signatory_name_set: bool
    vat_registered: bool
    can_issue_quotations: bool
    can_issue_invoices: bool
    missing: list[str]
