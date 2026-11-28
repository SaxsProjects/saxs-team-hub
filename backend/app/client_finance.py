"""Client follow-ups (payment reminders), statements of account and the monthly finance report.

Reminders move each open invoice on one stage at a time and never repeat a stage:

  1  friendly reminder, from 3 days before the due date
  2  payment overdue, from the day after the due date
  3  second notice, 7 days overdue
  4  final notice, 14 days overdue (the founder is told; a letter of demand is the founder's decision)

An invoice that is already several stages behind (for example when reminders are first switched on) gets only
the stage it has reached, not every earlier one. A client with reminders switched off, or with no email
address, gets nothing; the founder can switch all client emails off in Settings (`client_reminders`).
"""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .company import company_settings
from .emailer import OutgoingEmail, send_email
from .models import (
    AuditLog,
    Client,
    CreditNote,
    Document,
    Invoice,
    Payout,
    ProjectCost,
    Proposal,
    Quotation,
    Receipt,
    User,
)
from .notifications import notify_admins
from .numbering import allocate_number
from .payouts import format_zar
from .pdf_reports import finance_report_pdf, statement_of_account_pdf
from .services import audit, local_tz, store_document, today_local
from .vat import vat_position

log = logging.getLogger("teamhub.client_finance")

OPEN = ("issued", "part_paid")
PDF = "application/pdf"
STAGE_NAMES = {1: "Payment reminder", 2: "Payment overdue", 3: "Second notice", 4: "Final notice"}


# ---- Settings ------------------------------------------------------------------------------------


def autopilot_enabled(db: Session, key: str) -> bool:
    """Founder switches stored with the email preferences; on unless switched off."""
    prefs = db.scalar(select(User.notify_prefs).where(User.role == "admin").order_by(User.id).limit(1))
    return not (prefs and prefs.get(key) is False)


# ---- Reminders -----------------------------------------------------------------------------------


def reminder_stage_due(due: date | None, today: date) -> int:
    if due is None:
        return 0
    days = (today - due).days
    if days >= 14:
        return 4
    if days >= 7:
        return 3
    if days >= 1:
        return 2
    if days >= -3:
        return 1
    return 0


def _reminder_text(stage: int, inv: Invoice, s) -> str:
    balance = format_zar(inv.balance_cents)
    due = f"{inv.due_date:%d %B %Y}"
    hello = f"Dear {inv.client.contact_name or inv.client.name},"
    pay = (
        f"Please pay by EFT using {inv.number} as the payment reference and email the proof of payment to "
        f"{s.company_email or 'us'}. The invoice is attached."
    )
    if stage == 1:
        body = f"This is a friendly reminder that invoice {inv.number} ({inv.title}) for {balance} is due on {due}."
    elif stage == 2:
        body = f"Invoice {inv.number} ({inv.title}) was due on {due} and {balance} is still outstanding."
    elif stage == 3:
        body = (
            f"Our records show that invoice {inv.number} ({inv.title}) is now more than a week overdue. "
            f"The outstanding balance is {balance} (due {due})."
        )
    else:
        body = (
            f"This is a final notice: invoice {inv.number} ({inv.title}) has been overdue since {due} and {balance} "
            "remains unpaid. Please settle it within 7 days or contact us to agree on a payment arrangement."
        )
    already = "If you have already paid, thank you, and please ignore this message (payments can take a day to clear)."
    return "\n\n".join([hello, body, pay, already, "Kind regards", f"{s.company_legal_name}\n{s.company_email}".strip()])


def send_client_reminders(db: Session, today: date | None = None) -> int:
    """Email the next reminder for every open invoice that has reached a new stage. Returns how many were sent."""
    if not autopilot_enabled(db, "client_reminders"):
        return 0
    today = today or today_local()
    s = company_settings(db)
    sent = 0
    invoices = db.scalars(
        select(Invoice)
        .join(Client)
        .where(Invoice.status.in_(OPEN), Invoice.due_date.is_not(None), Client.reminders_enabled.is_(True))
    ).all()
    for inv in invoices:
        stage = reminder_stage_due(inv.due_date, today)
        if inv.balance_cents <= 0 or stage <= inv.reminder_stage or not inv.client.email:
            continue
        attachment = db.get(Document, inv.pdf_document_id) if inv.pdf_document_id else None
        msg = OutgoingEmail(
            to=inv.client.email,
            subject=f"{STAGE_NAMES[stage]}: invoice {inv.number} from {s.company_name}",
            text=_reminder_text(stage, inv, s),
            reply_to=s.company_email or None,
            attachments=[(f"{inv.number}.pdf", attachment.content, PDF)] if attachment else [],
        )
        if not send_email(msg):  # try again tomorrow
            continue
        inv.reminder_stage = stage
        inv.last_reminded_at = datetime.now(UTC)
        audit(db, "system", "invoice.reminder", "invoice", inv.id, after={"stage": stage})
        notify_admins(
            db,
            "invoices",
            f"{STAGE_NAMES[stage]} sent: {inv.number}",
            f"{inv.client.name} was reminded about {format_zar(inv.balance_cents)}"
            + (
                ". This was the final notice: decide whether to send a letter of demand (template in the library)."
                if stage == 4
                else "."
            ),
            "/finance/invoices",
        )
        sent += 1
    return sent


# ---- Statements of account -----------------------------------------------------------------------


def statement_items(db: Session, client: Client, as_of: date) -> tuple[list[Invoice], list[Receipt]]:
    invoices = [
        inv
        for inv in db.scalars(
            select(Invoice).where(Invoice.client_id == client.id, Invoice.status.in_(OPEN)).order_by(Invoice.due_date)
        )
        if inv.balance_cents > 0
    ]
    receipts = db.scalars(
        select(Receipt)
        .join(Invoice)
        .where(Invoice.client_id == client.id, Receipt.received_on > as_of - timedelta(days=90))
        .order_by(Receipt.received_on)
    ).all()
    return invoices, list(receipts)


def statement_preview(db: Session, client: Client) -> bytes:
    today = today_local()
    invoices, receipts = statement_items(db, client, today)
    return statement_of_account_pdf(client, invoices, receipts, as_of=today, number=None, company=company_settings(db))


def issue_statement(db: Session, client: Client, *, actor: str, email: bool) -> tuple[Document, str, bool]:
    """Number, store and (optionally) email a statement. Returns (document, number, emailed)."""
    today = today_local()
    s = company_settings(db)
    invoices, receipts = statement_items(db, client, today)
    number = allocate_number(db, "SOA")
    content = statement_of_account_pdf(client, invoices, receipts, as_of=today, number=number, company=s)
    stored = store_document(db, person_id=None, kind="statement", filename=f"{number}.pdf", content_type=PDF, content=content)
    emailed = False
    if email:
        if not client.email:
            raise ValueError("This client has no email address")
        balance = sum(i.balance_cents for i in invoices)
        emailed = send_email(
            OutgoingEmail(
                to=client.email,
                subject=f"Statement of account {number} from {s.company_name}",
                text="\n\n".join(
                    [
                        f"Dear {client.contact_name or client.name},",
                        f"Please find attached your statement of account as at {today:%d %B %Y}. "
                        f"The balance due is {format_zar(balance)}.",
                        f"Queries may be sent to {s.company_email or 'us'}.",
                        "Kind regards",
                        s.company_legal_name,
                    ]
                ),
                reply_to=s.company_email or None,
                attachments=[(f"{number}.pdf", content, PDF)],
            )
        )
    audit(db, actor, "statement.issue", "client", client.id, after={"number": number, "emailed": emailed})
    return stored, number, emailed


def send_monthly_statements(db: Session, today: date | None = None) -> int:
    """On the 1st of the month, email a statement to every client with an open balance (if switched on)."""
    today = today or today_local()
    if today.day != 1 or not autopilot_enabled(db, "client_statements"):
        return 0
    sent = 0
    for client in db.scalars(select(Client).where(Client.reminders_enabled.is_(True), Client.email.is_not(None))):
        invoices, _ = statement_items(db, client, today)
        if not invoices or _already_done(db, "statement.monthly", client.id, today):
            continue
        _, _, emailed = issue_statement(db, client, actor="system", email=True)
        if emailed:
            audit(db, "system", "statement.monthly", "client", client.id, after={"month": f"{today:%Y-%m}"})
            sent += 1
    return sent


def _already_done(db: Session, action: str, entity_id: int | None, today: date) -> bool:
    month = f"{today:%Y-%m}"
    for after in db.scalars(select(AuditLog.after).where(AuditLog.action == action, AuditLog.entity_id == entity_id)):
        if after and after.get("month") == month:
            return True
    return False


# ---- Monthly finance report ----------------------------------------------------------------------


def _month_bounds(month: date) -> tuple[date, date]:
    start = month.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def _utc(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=local_tz()).astimezone(UTC)


def _sum(db: Session, column, *where) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(column), 0)).where(*where)) or 0)


def finance_report(db: Session, month: date) -> dict:
    start, end = _month_bounds(month)
    issued = (Invoice.status.in_(("issued", "part_paid", "paid")), Invoice.issue_date >= start, Invoice.issue_date < end)
    invoiced_excl = _sum(db, Invoice.subtotal_cents, *issued)
    vat = _sum(db, Invoice.vat_cents, *issued)
    received = _sum(db, Receipt.amount_cents, Receipt.received_on >= start, Receipt.received_on < end)
    payouts_paid = _sum(db, Payout.amount_cents, Payout.paid_at >= _utc(start), Payout.paid_at < _utc(end))
    costs = _sum(db, ProjectCost.amount_cents, ProjectCost.incurred_at >= start, ProjectCost.incurred_at < end)
    as_of = min(end - timedelta(days=1), today_local())
    open_invoices = [inv for inv in db.scalars(select(Invoice).where(Invoice.status.in_(OPEN))) if inv.balance_cents > 0]
    overdue = [inv for inv in open_invoices if inv.due_date and inv.due_date < as_of]
    per_client: dict[int, dict] = {}
    for inv in db.scalars(select(Invoice).where(*issued)):
        row = per_client.setdefault(inv.client_id, {"name": inv.client.name, "count": 0, "total_cents": 0})
        row["count"] += 1
        row["total_cents"] += inv.total_cents
    position = vat_position(db, as_of)
    return {
        "month": start,
        "prepared_on": today_local(),
        "totals": {
            "invoiced_excl_cents": invoiced_excl,
            "vat_cents": vat,
            "invoiced_incl_cents": invoiced_excl + vat,
            "credited_cents": _sum(db, CreditNote.amount_cents, CreditNote.issue_date >= start, CreditNote.issue_date < end),
            "received_cents": received,
            "payouts_paid_cents": payouts_paid,
            "costs_cents": costs,
            "net_cash_cents": received - payouts_paid - costs,
        },
        "position": {
            "open_count": len(open_invoices),
            "outstanding_cents": sum(i.balance_cents for i in open_invoices),
            "overdue_count": len(overdue),
            "overdue_cents": sum(i.balance_cents for i in overdue),
            "payouts_unpaid_cents": _sum(db, Payout.amount_cents, Payout.paid_at.is_(None)),
            "quotations_open": int(
                db.scalar(select(func.count()).select_from(Quotation).where(Quotation.status == "issued")) or 0
            ),
            "proposals_open": int(db.scalar(select(func.count()).select_from(Proposal).where(Proposal.status == "issued")) or 0),
        },
        "clients": sorted(per_client.values(), key=lambda c: -c["total_cents"]),
        "vat": {
            "message": position.message,
            "compulsory_threshold_cents": position.compulsory_threshold_cents,
            "share_of_compulsory_bp": position.share_of_compulsory_bp,
        },
    }


def report_pdf(db: Session, month: date) -> bytes:
    return finance_report_pdf(finance_report(db, month), company=company_settings(db))


def send_monthly_report(db: Session, today: date | None = None) -> int:
    """On the 1st, email last month's finance report to the founder (once) and put it in the bell."""
    from .config import get_settings

    today = today or today_local()
    if today.day != 1 or _already_done(db, "report.monthly", None, today):
        return 0
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    content = report_pdf(db, last_month)
    settings = get_settings()
    if settings.admin_notify_email:
        send_email(
            OutgoingEmail(
                to=settings.admin_notify_email,
                subject=f"Finance report for {last_month:%B %Y}",
                text=f"The finance report for {last_month:%B %Y} is attached. It is also in the Team Hub under Reports.",
                attachments=[(f"SaxsProjects_Finance_Report_{last_month:%Y-%m}.pdf", content, PDF)],
            )
        )
    notify_admins(db, "reports", f"Finance report for {last_month:%B %Y} is ready", None, "/reports")
    audit(db, "system", "report.monthly", "report", None, after={"month": f"{today:%Y-%m}", "period": f"{last_month:%Y-%m}"})
    return 1
