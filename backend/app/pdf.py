"""Branded PDFs: offer acceptance records and contributor payout statements."""

from datetime import datetime

from fpdf import FPDF

from .config import get_settings
from .payouts import format_bp, format_zar

BLUE = (26, 95, 224)
NAVY = (21, 35, 63)
GREY = (90, 100, 115)


def _safe(text: object) -> str:
    # Built-in PDF fonts are Latin-1 only; replace anything else rather than fail.
    return str(text).replace("–", "-").replace("—", "-").encode("latin-1", "replace").decode("latin-1")


class _Doc(FPDF):
    def __init__(self, title: str):
        super().__init__(format="A4")
        self.doc_title = title
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 18, 18)
        self.add_page()

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*BLUE)
        self.cell(0, 8, _safe(get_settings().company_name), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 11)
        self.set_text_color(*NAVY)
        self.cell(0, 7, _safe(self.doc_title), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*BLUE)
        self.set_line_width(0.6)
        self.line(18, self.get_y() + 2, 192, self.get_y() + 2)
        self.ln(8)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, _safe(f"{get_settings().company_name} Team Hub - page {self.page_no()}"), align="C")

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
        "Calculation: net project income = amount received - direct project costs; "
        "earned = net project income x rate x work share. Each client payment pays out the "
        "amount newly earned since earlier payments. Payouts are due "
        f"{get_settings().payout_delay_days} days after the client payment is received.",
        size=9,
    )
    return bytes(doc.output())
