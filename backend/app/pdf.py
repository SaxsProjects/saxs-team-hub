"""Branded PDFs: quotations, invoices, receipts, credit notes, payout statements and offer acceptance records.

Documents the company signs carry the director's signature (see `load_signature`): issued quotations,
receipts, credit notes, payout statements and offer acceptance records. Drafts are never signed and
carry a DRAFT watermark. Invoices are not signed; they carry the banking details instead.
"""

import base64
import binascii
import io
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from .config import get_settings
from .payouts import format_bp, format_zar

BLUE = (26, 95, 224)
NAVY = (21, 35, 63)
GREY = (90, 100, 115)
RED = (200, 40, 40)

MAX_SIGNATURE_BYTES = 1_000_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


class SignatureError(RuntimeError):
    pass


@lru_cache
def load_signature() -> bytes | None:
    """The signature image from SIGNATURE_IMAGE_PATH or SIGNATURE_IMAGE_BASE64, or None if neither is set."""
    settings = get_settings()
    if settings.signature_image_path.strip():
        path = Path(settings.signature_image_path.strip())
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise SignatureError("SIGNATURE_IMAGE_PATH cannot be read") from exc
    elif settings.signature_image_base64.strip():
        try:
            data = base64.b64decode(settings.signature_image_base64.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SignatureError("SIGNATURE_IMAGE_BASE64 is not valid base64") from exc
    else:
        return None
    if len(data) > MAX_SIGNATURE_BYTES:
        raise SignatureError("The signature image is larger than 1 MB")
    if not (data.startswith(PNG_MAGIC) or data.startswith(JPEG_MAGIC)):
        raise SignatureError("The signature image must be a PNG or JPEG file")
    return data


def _safe(text: object) -> str:
    # Built-in PDF fonts are Latin-1 only; replace anything else rather than fail.
    return str(text).replace("–", "-").replace("—", "-").encode("latin-1", "replace").decode("latin-1")


def _d(day: date | None) -> str:
    return f"{day:%d %b %Y}" if day else "-"


class _Doc(FPDF):
    def __init__(self, title: str, watermark: str | None = None):
        super().__init__(format="A4")
        self.doc_title = title
        self.watermark = watermark
        self.set_title(_safe(title))
        self.set_author(_safe(get_settings().company_legal_name))
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 18, 18)
        self.add_page()

    def header(self):
        if self.watermark:
            with self.local_context(fill_opacity=0.15, text_color=RED):
                self.set_font("Helvetica", "B", 40)
                with self.rotation(35, x=105, y=150):
                    width = self.get_string_width(self.watermark)
                    self.text(105 - width / 2, 155, _safe(self.watermark))
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*BLUE)
        self.cell(0, 8, _safe(get_settings().company_name), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*NAVY)
        self.cell(0, 7, _safe(self.doc_title), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*BLUE)
        self.set_line_width(0.6)
        self.line(18, self.get_y() + 2, 192, self.get_y() + 2)
        self.ln(6)

    def footer(self):
        s = get_settings()
        parts = [s.company_legal_name]
        if s.company_registration_number:
            parts.append(f"Reg. {s.company_registration_number}")
        if s.company_vat_number:
            parts.append(f"VAT {s.company_vat_number}")
        parts.append(f"page {self.page_no()}")
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, _safe(" | ".join(parts)), align="C")

    def row(self, label: str, value: str, bold: bool = False):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*NAVY)
        self.cell(62, 7, _safe(label))
        self.set_font("Helvetica", "B" if bold else "", 10)
        self.multi_cell(0, 7, _safe(value), new_x="LMARGIN", new_y="NEXT")

    def para(self, text: str, size: int = 10):
        self.set_font("Helvetica", "", size)
        self.set_text_color(*GREY)
        self.multi_cell(0, 5.5, _safe(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def heading(self, text: str):
        self.ln(2)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*BLUE)
        self.cell(0, 6, _safe(text.upper()), new_x="LMARGIN", new_y="NEXT")

    def company_details(self):
        s = get_settings()
        lines = [s.company_legal_name]
        ids = []
        if s.company_registration_number:
            ids.append(f"Registration no. {s.company_registration_number}")
        if s.company_vat_number:
            ids.append(f"VAT no. {s.company_vat_number}")
        if ids:
            lines.append(" | ".join(ids))
        if s.company_address_lines:
            lines.append(", ".join(s.company_address_lines))
        contact = [v for v in (s.company_email, s.company_phone, s.company_website) if v]
        if contact:
            lines.append(" | ".join(contact))
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*GREY)
        for line in lines:
            self.cell(0, 4.6, _safe(line), new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def client_details(self, client, label: str = "Bill to"):
        self.heading(label)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*NAVY)
        self.cell(0, 5.5, _safe(client.name), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*GREY)
        details = []
        if client.registration_number:
            details.append(f"Registration no. {client.registration_number}")
        if client.contact_name:
            details.append(f"Attention: {client.contact_name}")
        if client.address:
            details.extend(line.strip() for line in client.address.splitlines() if line.strip())
        contact = [v for v in (client.email, client.phone) if v]
        if contact:
            details.append(" | ".join(contact))
        for line in details:
            self.cell(0, 4.6, _safe(line), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def line_table(self, lines):
        self.ln(2)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*NAVY)
        headings = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=NAVY)
        with self.table(
            col_widths=(100, 14, 30, 30),
            text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT"),
            headings_style=headings,
            line_height=6,
            borders_layout="HORIZONTAL_LINES",
        ) as table:
            table.row(["Description", "Qty", "Unit price", "Amount"])
            for line in lines:
                table.row(
                    [
                        _safe(line.description),
                        str(line.quantity),
                        format_zar(line.unit_price_cents),
                        format_zar(line.line_total_cents),
                    ]
                )
        self.ln(2)

    def total_row(self, label: str, cents: int, bold: bool = False):
        self.set_font("Helvetica", "B" if bold else "", 10)
        self.set_text_color(*NAVY)
        self.cell(144, 6.5, _safe(label), align="R")
        self.cell(30, 6.5, format_zar(cents), align="R", new_x="LMARGIN", new_y="NEXT")

    def totals(self, subtotal: int, vat: int, total: int, vat_rate_bp: int):
        if vat_rate_bp:
            self.total_row("Subtotal (excl. VAT)", subtotal)
            self.total_row(f"VAT at {format_bp(vat_rate_bp)}", vat)
        self.total_row("Total", total, bold=True)

    def signature_block(self, label: str, on: date | None = None):
        """The director's signature over their name, title and the date."""
        s = get_settings()
        if self.get_y() > 235:
            self.add_page()
        self.ln(6)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(0, 5, _safe(label), new_x="LMARGIN", new_y="NEXT")
        top = self.get_y()
        image = load_signature()
        if image:
            self.image(io.BytesIO(image), x=18, y=top + 1, h=16)
        else:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*RED)
            self.set_xy(18, top + 8)
            self.cell(0, 5, "Signature not configured")
        self.set_draw_color(*NAVY)
        self.set_line_width(0.3)
        self.line(18, top + 19, 88, top + 19)
        self.set_xy(18, top + 20)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*NAVY)
        name = s.signatory_name or "Authorised signatory"
        self.cell(0, 4.6, _safe(f"{name}, {s.signatory_title}"), new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 4.6, _safe(f"For and on behalf of {s.company_legal_name}"), new_x="LMARGIN", new_y="NEXT")
        if on:
            self.cell(0, 4.6, _safe(f"Date: {_d(on)}"), new_x="LMARGIN", new_y="NEXT")

    def blank_signature_block(self, label: str):
        """Empty lines for the client to sign, e.g. to accept a quotation."""
        if self.get_y() > 245:
            self.add_page()
        self.ln(6)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(0, 5, _safe(label), new_x="LMARGIN", new_y="NEXT")
        self.ln(8)
        self.set_font("Helvetica", "", 9)
        self.set_draw_color(*GREY)
        self.set_line_width(0.2)
        y = self.get_y()
        for x, text in ((18, "Name"), (78, "Signature"), (138, "Date")):
            self.line(x, y, x + 54, y)
            self.set_xy(x, y + 1)
            self.cell(54, 4.6, text)
        self.set_xy(18, y + 7)


# ---- Finance documents ---------------------------------------------------------------------------


def quotation_pdf(q, *, draft: bool) -> bytes:
    s = get_settings()
    doc = _Doc(f"QUOTATION {q.number or ''}".strip(), watermark="DRAFT - NOT ISSUED" if draft else None)
    doc.company_details()
    doc.row("Quotation number", q.number or "Draft (numbered when issued)")
    doc.row("Date", _d(q.issue_date))
    doc.row("Valid until", _d(q.valid_until))
    doc.row("Subject", q.title)
    doc.client_details(q.client, "Prepared for")
    doc.line_table(q.lines)
    doc.totals(q.subtotal_cents, q.vat_cents, q.total_cents, q.vat_rate_bp)
    doc.heading("Terms")
    vat_text = (
        f"Prices include VAT at {format_bp(q.vat_rate_bp)}."
        if q.vat_rate_bp
        else f"{s.company_legal_name} is not registered for VAT, so no VAT is charged."
    )
    doc.para(
        f"This quotation is valid for {s.quote_valid_days} days. A {s.deposit_percent}% deposit is payable before "
        f"work starts and the balance on completion. Invoices are payable within {s.invoice_due_days} days. "
        f"All amounts are in South African rand. {vat_text}",
        size=9,
    )
    if q.notes:
        doc.heading("Notes")
        doc.para(q.notes, size=9)
    if not draft:
        doc.signature_block("Issued by", q.issue_date)
    doc.blank_signature_block("Accepted by the client")
    return bytes(doc.output())


def invoice_pdf(inv, *, draft: bool) -> bytes:
    s = get_settings()
    title = "TAX INVOICE" if inv.vat_rate_bp else "INVOICE"
    doc = _Doc(f"{title} {inv.number or ''}".strip(), watermark="DRAFT - NOT VALID FOR PAYMENT" if draft else None)
    doc.company_details()
    doc.row("Invoice number", inv.number or "Draft (numbered when issued)")
    doc.row("Invoice date", _d(inv.issue_date))
    doc.row("Due date", _d(inv.due_date))
    if inv.quotation and inv.quotation.number:
        doc.row("Quotation reference", inv.quotation.number)
    doc.row("Subject", inv.title)
    doc.client_details(inv.client)
    doc.line_table(inv.lines)
    doc.totals(inv.subtotal_cents, inv.vat_cents, inv.total_cents, inv.vat_rate_bp)
    if inv.paid_cents or inv.credited_cents:
        if inv.credited_cents:
            doc.total_row("Credited", inv.credited_cents)
        if inv.paid_cents:
            doc.total_row("Paid", inv.paid_cents)
        doc.total_row("Balance due", inv.balance_cents, bold=True)
    doc.heading("Payment details")
    if s.bank_configured:
        doc.row("Bank", s.company_bank_name)
        doc.row("Account name", s.company_bank_account_name or s.company_legal_name)
        doc.row("Account number", s.company_bank_account_number)
        doc.row("Branch code", s.company_bank_branch_code)
        if s.company_bank_account_type:
            doc.row("Account type", s.company_bank_account_type)
        doc.row("Payment reference", inv.number or "(invoice number)", bold=True)
    else:
        doc.para("Banking details have not been configured yet.", size=9)
    doc.para(
        f"Please pay by the due date and use the invoice number as your payment reference. "
        f"Send proof of payment to {s.company_email or 'us'}."
        + ("" if inv.vat_rate_bp else f" {s.company_legal_name} is not registered for VAT."),
        size=9,
    )
    if inv.notes:
        doc.heading("Notes")
        doc.para(inv.notes, size=9)
    return bytes(doc.output())


def receipt_pdf(receipt, invoice) -> bytes:
    doc = _Doc(f"RECEIPT {receipt.number}")
    doc.company_details()
    doc.row("Receipt number", receipt.number)
    doc.row("Date issued", _d(receipt.issue_date))
    doc.client_details(invoice.client, "Received from")
    doc.row("Amount received", format_zar(receipt.amount_cents), bold=True)
    doc.row("Payment date", _d(receipt.received_on))
    doc.row("Payment method", {"eft": "EFT", "cash": "Cash", "card": "Card"}.get(receipt.method, "Other"))
    doc.row("Payment reference", receipt.reference)
    doc.row("For invoice", f"{invoice.number} - {invoice.title}")
    doc.row("Invoice total", format_zar(invoice.total_cents))
    doc.row("Balance outstanding", format_zar(invoice.balance_cents), bold=True)
    doc.signature_block("Received by", receipt.issue_date)
    return bytes(doc.output())


def credit_note_pdf(note, invoice) -> bytes:
    doc = _Doc(f"CREDIT NOTE {note.number}")
    doc.company_details()
    doc.row("Credit note number", note.number)
    doc.row("Date", _d(note.issue_date))
    doc.client_details(invoice.client, "Issued to")
    doc.row("Credits invoice", f"{invoice.number} dated {_d(invoice.issue_date)}")
    doc.row("Invoice total", format_zar(invoice.total_cents))
    doc.row("Amount credited", format_zar(note.amount_cents), bold=True)
    doc.row("Reason", note.reason)
    doc.row("Balance now due", format_zar(invoice.balance_cents), bold=True)
    doc.signature_block("Issued by", note.issue_date)
    return bytes(doc.output())


# ---- Team documents ------------------------------------------------------------------------------


def acceptance_record_pdf(
    *,
    reference: str,
    role: str,
    full_name: str,
    typed_signature: str,
    responded_at: datetime,
    ip: str | None,
    user_agent: str | None,
    offer_hash: str,
    pdf_sha256: str | None,
) -> bytes:
    doc = _Doc("Offer acceptance record")
    doc.para(
        "This record confirms that the offer below was accepted electronically by typing the "
        "candidate's full name as an electronic signature (Electronic Communications and "
        "Transactions Act 25 of 2002)."
    )
    doc.row("Offer reference", reference)
    doc.row("Role", role)
    doc.row("Candidate", full_name)
    doc.row("Typed signature", typed_signature, bold=True)
    doc.row("Accepted at (UTC)", responded_at.strftime("%Y-%m-%d %H:%M:%S"))
    doc.row("IP address", ip or "unknown")
    doc.row("Browser", (user_agent or "unknown")[:180])
    doc.row("Offer version hash", offer_hash)
    if pdf_sha256:
        doc.row("Proposal PDF SHA-256", pdf_sha256)
    doc.signature_block("Offer made by", responded_at.date())
    return bytes(doc.output())


def payout_statement_pdf(
    *,
    statement_number: str,
    project_name: str,
    client_name: str,
    contributor: str,
    payment_date: str,
    payment_reference: str,
    calc: dict,
    due_at: str,
    paid_at: str | None,
    eft_reference: str | None,
    issued_on: date | None = None,
) -> bytes:
    doc = _Doc(f"Contributor payout statement {statement_number}")
    doc.row("Contributor", contributor)
    doc.row("Project", f"{project_name} ({client_name})")
    doc.row("Client payment", f"{payment_date} - ref {payment_reference}")
    doc.ln(2)
    doc.row("Received from client to date", format_zar(calc["received_to_date_cents"]))
    doc.row("Direct project costs to date", format_zar(calc["costs_to_date_cents"]))
    doc.row("Net project income", format_zar(calc["net_income_cents"]), bold=True)
    doc.row("Your rate", format_bp(calc["rate_bp"]))
    doc.row("Your agreed work share", format_bp(calc["work_share_bp"]))
    doc.row("Earned to date", format_zar(calc["earned_to_date_cents"]))
    doc.row("Already paid on earlier instalments", format_zar(calc["previously_allocated_cents"]))
    doc.row("Payout for this payment", format_zar(calc["payout_cents"]), bold=True)
    doc.ln(2)
    doc.row("Due date", due_at)
    doc.row("Paid", f"{paid_at} - EFT ref {eft_reference}" if paid_at else "Not yet paid")
    doc.ln(4)
    doc.para(
        "Calculation: net project income = amount received (excluding VAT) - direct project costs; "
        "earned = net project income x rate x work share. Each client payment pays out the "
        "amount newly earned since earlier payments. Payouts are due "
        f"{get_settings().payout_delay_days} days after the client payment is received.",
        size=9,
    )
    doc.signature_block("Issued by", issued_on)
    return bytes(doc.output())
