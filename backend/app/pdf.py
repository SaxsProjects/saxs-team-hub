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

from .config import Settings, get_settings
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


# ---- Layout: the company templates (Documents/SaxsProjects Proposals/Templates) -------------------
# Logo and company block, blue rule, large blue title with the numbers on the right, FROM / TO side by
# side, a light-blue box, a navy-headed striped table, notes on the left with the totals and a blue
# amount bar on the right, and the company line in the footer.

LOGO = Path(__file__).parent / "assets" / "logo-full.png"
LIGHT = (234, 241, 253)  # boxes
STRIPE = (243, 247, 254)  # alternate table rows
RULE = (96, 132, 214)
LEFT, RIGHT, WIDTH = 18, 192, 174
BOTTOM = 271  # content stops here; the footer sits below


class _Doc(FPDF):
    def __init__(self, title: str, watermark: str | None = None, company: Settings | None = None, reference: str = ""):
        super().__init__(format="A4")
        # Company details to print: the server settings with the founder's saved details on top (app/company.py).
        self.s = company or get_settings()
        self.doc_title = title
        self.watermark = watermark
        self.set_title(_safe(f"{title} {reference}".strip()))
        self.set_author(_safe(self.s.company_legal_name))
        self.set_auto_page_break(auto=True, margin=297 - BOTTOM)
        self.set_margins(LEFT, 18, 210 - RIGHT)
        self.add_page()

    # -- page furniture --
    def header(self):
        if self.watermark:
            with self.local_context(fill_opacity=0.15, text_color=RED):
                self.set_font("Helvetica", "B", 40)
                with self.rotation(35, x=105, y=150):
                    width = self.get_string_width(self.watermark)
                    self.text(105 - width / 2, 155, _safe(self.watermark))
        s = self.s
        if LOGO.exists():
            self.image(str(LOGO), x=LEFT - 2, y=9, h=27)
        else:
            self.set_xy(LEFT, 14)
            self.set_font("Helvetica", "B", 18)
            self.set_text_color(*BLUE)
            self.cell(80, 9, _safe(s.company_name))
        self.set_xy(90, 15)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*NAVY)
        self.cell(RIGHT - 90, 6, _safe(s.company_legal_name), align="R")
        lines = [(s.company_tagline, GREY)]
        contact = " | ".join(v for v in (s.company_email, s.company_phone) if v)
        if contact:
            lines.append((contact, NAVY))
        self.set_font("Helvetica", "", 9.5)
        for i, (text, colour) in enumerate(lines):
            self.set_xy(90, 22 + i * 5.5)
            self.set_text_color(*colour)
            self.cell(RIGHT - 90, 5, _safe(text), align="R")
        self.set_draw_color(*RULE)
        self.set_line_width(0.6)
        self.line(LEFT, 38, RIGHT, 38)
        self.set_y(45)

    def footer(self):
        s = self.s
        self.set_draw_color(*NAVY)
        self.set_line_width(0.5)
        self.line(LEFT, 279, RIGHT, 279)
        parts = [s.company_legal_name]
        if s.company_registration_number:
            parts.append(f"Registration No: {s.company_registration_number}")
        if s.company_vat_number:
            parts.append(f"VAT No: {s.company_vat_number}")
        if s.company_email:
            parts.append(s.company_email)
        if s.company_slogan:
            parts.append(s.company_slogan)
        self.set_y(281)
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(*NAVY)
        self.cell(0, 5, _safe(" | ".join(parts)), align="C")
        self.set_y(286)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*GREY)
        self.cell(0, 4, f"Page {self.page_no()} of {{nb}}", align="C")

    # -- building blocks --
    def title_block(self, meta: list[tuple[str, str]]):
        y = self.get_y()
        size = 22
        self.set_font("Helvetica", "B", size)
        while self.get_string_width(_safe(self.doc_title)) > (100 if meta else WIDTH) and size > 13:
            size -= 1
            self.set_font("Helvetica", "B", size)
        self.set_text_color(*BLUE)
        self.set_xy(LEFT, y)
        self.cell(0, 11, _safe(self.doc_title))
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(*NAVY)
        for i, (label, value) in enumerate(meta):
            self.set_xy(110, y + 1 + i * 5)
            self.cell(RIGHT - 110, 5, _safe(f"{label}: {value}"), align="R")
        self.set_y(max(y + 13, y + 2 + len(meta) * 5) + 3)

    def from_lines(self) -> list[str]:
        s = self.s
        lines = [s.company_legal_name]
        if s.company_registration_number:
            lines.append(f"Registration No: {s.company_registration_number}")
        if s.company_vat_number:
            lines.append(f"VAT No: {s.company_vat_number}")
        lines.extend(s.company_address_lines)
        whatsapp = f"WhatsApp: {s.company_whatsapp}" if s.company_whatsapp else ""
        for group in ((s.company_email, s.company_phone), (whatsapp, s.company_website)):
            text = "  |  ".join(v for v in group if v)
            if text:
                lines.append(text)
        return lines

    @staticmethod
    def client_lines(client) -> list[str]:
        lines = [client.name]
        if client.registration_number:
            lines.append(f"Registration No: {client.registration_number}")
        if client.contact_name:
            lines.append(f"Attention: {client.contact_name}")
        if client.address:
            lines.extend(line.strip() for line in client.address.splitlines() if line.strip())
        contact = "  |  ".join(v for v in (client.email, client.phone) if v)
        if contact:
            lines.append(contact)
        return lines

    def parties(self, left_label: str, left: list[str], right_label: str, right: list[str]):
        y = self.get_y()

        def column(x: float, label: str, lines: list[str]) -> float:
            self.set_xy(x, y)
            self.set_font("Helvetica", "B", 9.5)
            self.set_text_color(*NAVY)
            self.cell(84, 5, _safe(label.upper()))
            yy = y + 5.5
            for i, line in enumerate(lines):
                self.set_xy(x, yy)
                self.set_font("Helvetica", "B" if i == 0 else "", 9.5)
                self.multi_cell(84, 4.8, _safe(line))
                yy = self.get_y()
            return yy

        end = max(column(LEFT, left_label, left), column(110, right_label, right))
        self.set_y(end + 4)

    def section_label(self, text: str, colour=BLUE):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*colour)
        self.cell(0, 6, _safe(text.upper()), new_x="LMARGIN", new_y="NEXT")

    def box(self, heading: str, lines: list[str], italic: bool = False):
        """A heading over a light-blue box, as for the banking details or project scope."""
        self.set_font("Helvetica", "I" if italic else "", 9.5)
        count = sum(len(self.multi_cell(WIDTH - 10, 5, _safe(line), dry_run=True, output="LINES")) for line in lines)
        height = count * 5 + 6
        if self.get_y() + 7 + height > BOTTOM:
            self.add_page()
        self.section_label(heading)
        y = self.get_y() + 1
        self.set_fill_color(*LIGHT)
        self.rect(LEFT, y, WIDTH, height, style="F")
        self.set_xy(LEFT + 5, y + 3)
        self.set_font("Helvetica", "I" if italic else "", 9.5)
        self.set_text_color(*NAVY)
        for line in lines:
            self.set_x(LEFT + 5)
            self.multi_cell(WIDTH - 10, 5, _safe(line), new_x="LMARGIN", new_y="NEXT")
        self.set_y(y + height + 4)

    def table_rows(self, headings: list[str], rows: list[list[str]], widths: tuple, aligns: tuple):
        """Navy heading row, then light-blue stripes on every other row, numbered in the first column."""
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(*NAVY)
        with self.table(
            width=WIDTH,
            col_widths=widths,
            text_align=aligns,
            headings_style=FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=NAVY),
            line_height=5.2,
            borders_layout="NONE",
            cell_fill_color=STRIPE,
            cell_fill_mode="ROWS",
            padding=(1.2, 3),
        ) as table:
            table.row([_safe(h) for h in headings])
            for row in rows:
                table.row([_safe(cell) for cell in row])
        self.ln(3)

    def line_table(self, lines):
        rows = [
            [str(i), line.description, str(line.quantity), format_zar(line.unit_price_cents), format_zar(line.line_total_cents)]
            for i, line in enumerate(lines, start=1)
        ]
        self.table_rows(
            ["#", "Description", "Qty", "Unit price", "Amount"],
            rows,
            (8, 94, 14, 29, 29),
            ("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"),
        )

    def bottom(self, notes: list[tuple[str, str]], totals: list[tuple[str, str]], bar_label: str, bar_value: str):
        """Notes on the left; the totals and the blue amount bar on the right."""
        if self.get_y() > 205:
            self.add_page()
        y = self.get_y()
        ty = y
        self.set_text_color(*NAVY)
        for label, value in totals:
            self.set_font("Helvetica", "", 9.5)
            self.set_xy(118, ty)
            self.cell(40, 5.5, _safe(label))
            self.cell(RIGHT - 158, 5.5, _safe(value), align="R")
            ty += 5.5
        ty += 3 if totals else 0
        self.set_fill_color(*BLUE)
        self.rect(116, ty, RIGHT - 116, 10, style="F")
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 9)
        self.set_xy(119, ty)
        self.cell(RIGHT - 122, 10, _safe(bar_label))
        self.set_font("Helvetica", "B", 10.5)
        self.set_xy(119, ty)
        self.cell(RIGHT - 122, 10, _safe(bar_value), align="R")
        ty += 10
        self.bar_end = ty
        ly = y
        for heading, text in notes:
            self.set_xy(LEFT, ly)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*NAVY)
            self.cell(92, 5, _safe(heading.upper()))
            self.set_xy(LEFT, ly + 5)
            self.set_font("Helvetica", "", 8.8)
            self.set_text_color(*GREY)
            self.multi_cell(92, 4.3, _safe(text))
            ly = self.get_y() + 2.5
        self.set_y(max(ly, ty) + 3)

    def closing(self, heading: str, text: str):
        if self.get_y() > BOTTOM - 14:
            self.add_page()
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(0, 5, _safe(heading.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 8.8)
        self.set_text_color(*GREY)
        self.multi_cell(0, 4.4, _safe(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def row(self, label: str, value: str, bold: bool = False):
        self.set_font("Helvetica", "B", 9.5)
        self.set_text_color(*NAVY)
        self.cell(62, 6.5, _safe(label))
        self.set_font("Helvetica", "B" if bold else "", 9.5)
        self.multi_cell(0, 6.5, _safe(value), new_x="LMARGIN", new_y="NEXT")

    def para(self, text: str, size: float = 9.5):
        self.set_font("Helvetica", "", size)
        self.set_text_color(*GREY)
        self.multi_cell(0, 5, _safe(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def signature_block(self, label: str, on: date | None = None, at: tuple[float, float] | None = None):
        """The director's signature over their name, title and the date; `at` places it (x, y) instead of
        below the content, e.g. in the free space under the amount bar."""
        s = self.s
        x = LEFT
        below = self.get_y()
        if at and at[1] + 38 <= BOTTOM:
            x, y = at
            self.set_xy(x, y)
        else:
            at = None
            if self.get_y() > BOTTOM - 40:
                self.add_page()
            self.ln(3)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.set_x(x)
        self.cell(0, 5, _safe(label.upper()), new_x="LMARGIN", new_y="NEXT")
        top = self.get_y()
        self.last_signature_top = top
        image = load_signature()
        if image:
            self.image(io.BytesIO(image), x=x, y=top + 1, h=16)
        else:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*RED)
            self.set_xy(x, top + 8)
            self.cell(0, 5, "Signature not configured")
        self.set_draw_color(*NAVY)
        self.set_line_width(0.3)
        self.line(x, top + 19, x + 70, top + 19)
        self.set_y(top + 20)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*NAVY)
        name = s.signatory_name or "Authorised signatory"
        lines = [f"{name}, {s.signatory_title}", f"For and on behalf of {s.company_legal_name}"]
        if on:
            lines.append(f"Date: {_d(on)}")
        for line in lines:
            self.set_x(x)
            self.cell(0, 4.6, _safe(line), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)
        if at:
            self.set_y(max(self.get_y(), below))

    def client_acceptance_beside(self, label: str, text: str, top: float):
        """The client's sign-off lines in the right half, level with the company signature at `top`."""
        x = 110
        self.set_xy(x, top - 5)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(RIGHT - x, 5, _safe(label.upper()))
        self.set_xy(x, top)
        self.set_font("Helvetica", "", 8.8)
        self.set_text_color(*GREY)
        self.cell(RIGHT - x, 4.6, _safe(text))
        self.set_draw_color(*GREY)
        self.set_line_width(0.2)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*NAVY)
        for i, field in enumerate(("Name", "Signature", "Date")):
            y = top + 11 + i * 7
            self.set_xy(x, y - 4.6)
            self.cell(20, 4.6, field)
            self.line(x + 20, y, RIGHT, y)

    def blank_signature_block(self, label: str, text: str = ""):
        """Empty lines for the client to sign, e.g. to accept a quotation."""
        if self.get_y() > BOTTOM - 26:
            self.add_page()
        self.ln(4)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(0, 5, _safe(label.upper()), new_x="LMARGIN", new_y="NEXT")
        if text:
            self.set_font("Helvetica", "", 8.8)
            self.set_text_color(*GREY)
            self.cell(0, 4.6, _safe(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(9)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*NAVY)
        self.set_draw_color(*GREY)
        self.set_line_width(0.2)
        y = self.get_y()
        for x, label_text in ((LEFT, "Name"), (LEFT + 60, "Signature"), (LEFT + 120, "Date")):
            self.line(x, y, x + 54, y)
            self.set_xy(x, y + 1)
            self.cell(54, 4.6, label_text)
        self.set_xy(LEFT, y + 7)


def _vat_totals(subtotal: int, vat: int, vat_rate_bp: int) -> list[tuple[str, str]]:
    if vat_rate_bp:
        return [("Subtotal (excl. VAT)", format_zar(subtotal)), (f"VAT at {format_bp(vat_rate_bp)}", format_zar(vat))]
    return [("Subtotal", format_zar(subtotal))]


def _queries(s: Settings, what: str) -> str:
    where = s.company_email or "us"
    whatsapp = f" or WhatsApp {s.company_whatsapp}" if s.company_whatsapp else ""
    return f"Queries about this {what} may be sent to {where}{whatsapp}."


def _short(text: str, limit: int = 44) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


# ---- Finance documents ---------------------------------------------------------------------------


def quotation_pdf(q, *, draft: bool, company: Settings | None = None) -> bytes:
    s = company or get_settings()
    doc = _Doc("QUOTATION", watermark="DRAFT - NOT ISSUED" if draft else None, company=company, reference=q.number or "")
    doc.title_block(
        [
            ("Quotation No", q.number or "Draft (numbered when issued)"),
            ("Date", _d(q.issue_date)),
            ("Valid until", f"{_d(q.valid_until)} ({s.quote_valid_days} days)"),
        ]
    )
    doc.parties("From", doc.from_lines(), "Quotation for", doc.client_lines(q.client))
    doc.box("Project scope", [q.title])
    doc.line_table(q.lines)
    vat_text = (
        f"Prices include VAT at {format_bp(q.vat_rate_bp)}."
        if q.vat_rate_bp
        else f"{s.company_legal_name} is not registered for VAT, so no VAT is charged."
    )
    notes = [
        (
            "Payment terms",
            f"{s.deposit_percent}% deposit before work begins; balance on completion and handover. Invoices are payable "
            f"within {s.invoice_due_days} days. All prices are in South African Rand. {vat_text}",
        ),
        (
            "Conditions",
            f"This quotation is valid for {s.quote_valid_days} days. Work begins once the signed acceptance and deposit "
            "are received. Changes to the scope are quoted separately.",
        ),
    ]
    if q.notes:
        notes.append(("Notes", q.notes))
    doc.bottom(notes, _vat_totals(q.subtotal_cents, q.vat_cents, q.vat_rate_bp), "TOTAL (ZAR)", format_zar(q.total_cents))
    if draft:
        doc.blank_signature_block("Client acceptance", "I accept this quotation and its conditions.")
    else:
        if doc.get_y() > BOTTOM - 40:
            doc.add_page()
        doc.signature_block("Issued by", q.issue_date)
        doc.client_acceptance_beside("Client acceptance", "I accept this quotation and its conditions.", doc.last_signature_top)
    return bytes(doc.output())


def invoice_pdf(inv, *, draft: bool, company: Settings | None = None) -> bytes:
    s = company or get_settings()
    title = "TAX INVOICE" if inv.vat_rate_bp else "INVOICE"
    doc = _Doc(title, watermark="DRAFT - NOT VALID FOR PAYMENT" if draft else None, company=company, reference=inv.number or "")
    meta = [
        ("Invoice No", inv.number or "Draft (numbered when issued)"),
        ("Invoice date", _d(inv.issue_date)),
        ("Due date", f"{_d(inv.due_date)} ({s.invoice_due_days} days)"),
    ]
    if inv.quotation and inv.quotation.number:
        meta.append(("Quotation ref", inv.quotation.number))
    meta.append(("For", _short(inv.title)))
    doc.title_block(meta)
    doc.parties("From", doc.from_lines(), "Bill to", doc.client_lines(inv.client))
    if s.bank_configured:
        second = [f"Branch code: {s.company_bank_branch_code}"]
        if s.company_bank_account_type:
            second.append(f"Account type: {s.company_bank_account_type}")
        second.append(f"Payment reference: {inv.number or 'the invoice number'}")
        banking = [
            f"Bank: {s.company_bank_name}     Account name: {s.company_bank_account_name or s.company_legal_name}     "
            f"Account no: {s.company_bank_account_number}",
            "     ".join(second),
        ]
    else:
        banking = ["Banking details have not been configured yet."]
    doc.box("Banking details", banking)
    doc.line_table(inv.lines)
    totals = _vat_totals(inv.subtotal_cents, inv.vat_cents, inv.vat_rate_bp)
    if inv.vat_rate_bp:
        totals.append(("Total", format_zar(inv.total_cents)))
    if inv.credited_cents:
        totals.append(("Less credited", format_zar(inv.credited_cents)))
    if inv.paid_cents:
        totals.append(("Less paid", format_zar(inv.paid_cents)))
    notes = [
        (
            "Payment terms",
            f"Payment is due within {s.invoice_due_days} days of the invoice date. Please use the invoice number as your "
            f"payment reference and email proof of payment to {s.company_email or 'us'}."
            + ("" if inv.vat_rate_bp else f" {s.company_legal_name} is not registered for VAT."),
        ),
        (
            "Ownership",
            "Ownership of the delivered work passes to the client once this invoice is paid in full, as set out in the "
            "client service agreement.",
        ),
    ]
    if inv.notes:
        notes.append(("Notes", inv.notes))
    doc.bottom(notes, totals, "AMOUNT DUE (ZAR)", format_zar(inv.balance_cents))
    doc.closing("Thank you for your business", _queries(s, "invoice"))
    return bytes(doc.output())


PREVIEW_MARK = "PREVIEW - NOT ISSUED"


def _preview_footer(doc: "_Doc") -> None:
    """Previews are never signed: the signature and the number are added only when the document is issued."""
    doc.ln(2)
    doc.para("Preview only. The number, date and signature are added when it is issued.", size=9)


_METHODS = {"eft": "EFT", "cash": "Cash", "card": "Card"}


def receipt_pdf(receipt, invoice, *, company: Settings | None = None, preview: bool = False) -> bytes:
    s = company or get_settings()
    doc = _Doc(
        "RECEIPT", watermark=PREVIEW_MARK if preview else None, company=company, reference="" if preview else receipt.number
    )
    doc.title_block(
        [("Receipt No", receipt.number), ("Date received", _d(receipt.received_on)), ("Invoice paid", invoice.number or "-")]
    )
    doc.parties("From", doc.from_lines(), "Received from", doc.client_lines(invoice.client))
    doc.box(
        "Payment details",
        [
            f"Payment method: {_METHODS.get(receipt.method, 'Other')}     Payment reference: {receipt.reference}     "
            f"Date paid: {_d(receipt.received_on)}"
        ],
    )
    doc.table_rows(
        ["#", "Payment for", "Reference", "Amount"],
        [["1", f"{invoice.number} - {invoice.title}", receipt.reference, format_zar(receipt.amount_cents)]],
        (8, 100, 37, 29),
        ("LEFT", "LEFT", "LEFT", "RIGHT"),
    )
    credited = getattr(invoice, "credited_cents", 0) or 0
    previously = max(0, invoice.total_cents - credited - invoice.balance_cents - receipt.amount_cents)
    totals = [("Invoice total", format_zar(invoice.total_cents))]
    if credited:
        totals.append(("Credited", format_zar(credited)))
    totals += [("Previously paid", format_zar(previously)), ("Balance outstanding", format_zar(invoice.balance_cents))]
    doc.bottom(
        [
            (
                "Confirmation",
                f"This receipt confirms that {s.company_legal_name} has received the payment set out above. "
                "Please keep it for your records.",
            ),
            ("Queries", f"If any detail on this receipt is incorrect, please contact {s.company_email or 'us'} within 7 days."),
        ],
        totals,
        "AMOUNT RECEIVED (ZAR)",
        format_zar(receipt.amount_cents),
    )
    doc.closing("Thank you for your payment", f"{s.company_name} appreciates your business.")
    if preview:
        _preview_footer(doc)
    else:
        doc.signature_block("Issued by", receipt.issue_date)
    return bytes(doc.output())


def credit_note_pdf(note, invoice, *, company: Settings | None = None, preview: bool = False) -> bytes:
    s = company or get_settings()
    doc = _Doc(
        "CREDIT NOTE", watermark=PREVIEW_MARK if preview else None, company=company, reference="" if preview else note.number
    )
    doc.title_block(
        [
            ("Credit note No", note.number),
            ("Date", _d(note.issue_date)),
            ("Credits invoice", invoice.number or "-"),
        ]
    )
    doc.parties("From", doc.from_lines(), "Issued to", doc.client_lines(invoice.client))
    doc.box("Reason", [note.reason])
    doc.table_rows(
        ["#", "Credit against", "Invoice date", "Amount"],
        [["1", f"{invoice.number} - {invoice.title}", _d(invoice.issue_date), format_zar(note.amount_cents)]],
        (8, 100, 37, 29),
        ("LEFT", "LEFT", "LEFT", "RIGHT"),
    )
    doc.bottom(
        [
            (
                "About this credit note",
                f"This credit note reduces the amount owed on invoice {invoice.number} by the amount shown. "
                "No payment is due for the credited amount.",
            ),
            ("Queries", _queries(s, "credit note")),
        ],
        [("Invoice total", format_zar(invoice.total_cents)), ("Balance now due", format_zar(invoice.balance_cents))],
        "AMOUNT CREDITED (ZAR)",
        format_zar(note.amount_cents),
    )
    if preview:
        _preview_footer(doc)
    else:
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
    company: Settings | None = None,
) -> bytes:
    from .services import local_tz

    doc = _Doc("OFFER ACCEPTANCE RECORD", company=company, reference=reference)
    doc.title_block([])
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
    doc.signature_block("Offer made by", responded_at.astimezone(local_tz()).date())
    return bytes(doc.output())


def _statement_bottom(doc: _Doc, *, due: str, paid_at: str | None, eft_reference: str | None, amount_cents: int, notes):
    s = doc.s
    doc.bottom(
        notes
        + [
            (
                "Tax",
                "You are engaged as an independent contractor and are responsible for declaring this income to SARS.",
            ),
            ("Queries", f"Please raise any query about this statement within 14 days by email to {s.company_email or 'us'}."),
        ],
        [("Due date", due), ("Date paid", paid_at or "Not yet paid"), ("EFT reference", _short(eft_reference or "-", 16))],
        "AMOUNT PAID (ZAR)" if paid_at else "AMOUNT DUE (ZAR)",
        format_zar(amount_cents),
    )


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
    company: Settings | None = None,
) -> bytes:
    doc = _Doc("PAYOUT STATEMENT", company=company, reference=statement_number)
    doc.title_block(
        [("Statement No", statement_number), ("Statement date", _d(issued_on)), ("Client payment date", payment_date)]
    )
    doc.parties(
        "Contractor",
        [contributor],
        "Project",
        [project_name, f"Client: {client_name}", f"Client payment ref: {payment_reference}"],
    )
    doc.box(
        "Calculation basis",
        [
            "Net project income = amount received from the client (excluding VAT) less direct project costs.",
            "Payout = net project income x rate x agreed work share, each instalment at the rate in force on the day it "
            "was received.",
        ],
    )
    rows = [
        ["Amount received from the client to date", format_zar(calc["received_to_date_cents"])],
        ["Less direct project costs to date (hosting, domains, tools, payment fees)", format_zar(calc["costs_to_date_cents"])],
        ["Net project income", format_zar(calc["net_income_cents"])],
    ]
    segments = calc.get("rate_segments") or []
    if segments:
        rows += [
            [f"Instalment {seg['label']}: net income at {format_bp(seg['rate_bp'])}", format_zar(seg["net_cents"])]
            for seg in segments
        ]
    else:
        rows.append(["Contractor rate", format_bp(calc["rate_bp"])])
    rows += [
        ["Agreed work share", format_bp(calc["work_share_bp"])],
        ["Earned to date (net project income x rate x work share)", format_zar(calc["earned_to_date_cents"])],
        ["Less already paid on earlier instalments", format_zar(calc["previously_allocated_cents"])],
        ["Payout for this payment", format_zar(calc["payout_cents"])],
    ]
    doc.table_rows(
        ["#", "Item", "Amount"],
        [[str(i), *row] for i, row in enumerate(rows, start=1)],
        (8, 136, 30),
        ("LEFT", "LEFT", "RIGHT"),
    )
    _statement_bottom(
        doc,
        due=due_at,
        paid_at=paid_at,
        eft_reference=eft_reference,
        amount_cents=calc["payout_cents"],
        notes=[
            (
                "Notes",
                "Calculated in line with the Independent Contractor Agreement. Costs are set against the earliest "
                "instalments, and each client payment pays out the amount newly earned since earlier payments. No payout "
                f"is due on amounts not yet received from the client. Payouts are due {get_settings().payout_delay_days} "
                "days after the client payment is received.",
            )
        ],
    )
    doc.signature_block("Issued by", issued_on, at=(118, doc.bar_end + 8))
    return bytes(doc.output())


def task_fee_statement_pdf(
    *,
    statement_number: str,
    contributor: str,
    task_number: str,
    title: str,
    deliverable: str,
    fee_cents: int,
    accepted_on: str,
    due_at: str | None,
    paid_at: str | None,
    eft_reference: str | None,
    issued_on: date | None = None,
    company: Settings | None = None,
) -> bytes:
    doc = _Doc("TASK FEE STATEMENT", company=company, reference=statement_number)
    doc.title_block([("Statement No", statement_number), ("Statement date", _d(issued_on)), ("Task accepted on", accepted_on)])
    doc.parties("Contractor", [contributor], "Task Order", [task_number, title])
    doc.box("Deliverable", [deliverable[:300]])
    doc.table_rows(
        ["#", "Item", "Amount"],
        [["1", f"Task fee for {task_number} (as recorded in the Task Order)", format_zar(fee_cents)]],
        (8, 136, 30),
        ("LEFT", "LEFT", "RIGHT"),
    )
    _statement_bottom(
        doc,
        due=due_at or "See clause 5",
        paid_at=paid_at,
        eft_reference=eft_reference,
        amount_cents=fee_cents,
        notes=[
            (
                "Notes",
                "The fee is the amount recorded in the Task Order. It is due 7 days after the task is accepted, or, for "
                "tasks accepted before the Company's First Client Payment under deferred terms, within 30 days after "
                "that payment (see your agreement, clause 5).",
            )
        ],
    )
    doc.signature_block("Issued by", issued_on, at=(118, doc.bar_end + 8))
    return bytes(doc.output())
