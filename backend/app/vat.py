"""Watch the VAT registration thresholds so the company registers on time (VAT Act 89 of 1991, section 23).

Taxable supplies are measured as the value of invoices issued in the last 12 months, excluding VAT and less
credit notes. Before registration every supply SaxsProjects makes is a taxable supply at the standard rate.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .company import company_settings
from .finance import excluding_vat
from .models import Invoice
from .payouts import format_zar

WARN_SHARE = 0.8  # warn when supplies reach 80% of the compulsory threshold


@dataclass
class VatPosition:
    registered: bool
    vat_number: str | None
    rate_bp: int
    taxable_12m_cents: int
    compulsory_threshold_cents: int
    voluntary_threshold_cents: int
    share_of_compulsory_bp: int
    status: str  # registered | below | voluntary_possible | approaching | must_register
    message: str


def taxable_supplies(db: Session, today: date) -> int:
    since = today - timedelta(days=365)
    total = 0
    for inv in db.scalars(
        select(Invoice).where(
            Invoice.status.in_(("issued", "part_paid", "paid")), Invoice.issue_date > since, Invoice.issue_date <= today
        )
    ):
        total += inv.subtotal_cents - excluding_vat(inv.credited_cents, inv.subtotal_cents, inv.total_cents)
    return max(total, 0)


def vat_position(db: Session, today: date) -> VatPosition:
    s = company_settings(db)
    supplies = taxable_supplies(db, today)
    compulsory, voluntary = s.vat_compulsory_threshold_cents, s.vat_voluntary_threshold_cents
    share = round(supplies * 10_000 / compulsory) if compulsory else 0
    if s.vat_registered:
        status, message = "registered", f"Registered for VAT ({s.company_vat_number}). Invoices are tax invoices with VAT."
    elif supplies > compulsory:
        status = "must_register"
        message = (
            f"Taxable supplies in the last 12 months are {format_zar(supplies)}, above the {format_zar(compulsory)} "
            "threshold. Apply to SARS for VAT registration within 21 days of passing it, then add the VAT number in "
            "Settings so invoices become tax invoices."
        )
    elif supplies >= compulsory * WARN_SHARE:
        status = "approaching"
        message = (
            f"Taxable supplies in the last 12 months are {format_zar(supplies)}, {share / 100:.0f}% of the "
            f"{format_zar(compulsory)} compulsory VAT threshold. Prepare to register for VAT."
        )
    elif supplies >= voluntary:
        status = "voluntary_possible"
        message = (
            f"Taxable supplies in the last 12 months are {format_zar(supplies)}. Voluntary VAT registration is possible "
            f"from {format_zar(voluntary)}; it is compulsory above {format_zar(compulsory)}."
        )
    else:
        status = "below"
        message = f"Not registered for VAT. Taxable supplies in the last 12 months: {format_zar(supplies)}."
    return VatPosition(
        registered=s.vat_registered,
        vat_number=s.company_vat_number or None,
        rate_bp=s.vat_rate_bp if s.vat_registered else 0,
        taxable_12m_cents=supplies,
        compulsory_threshold_cents=compulsory,
        voluntary_threshold_cents=voluntary,
        share_of_compulsory_bp=share,
        status=status,
        message=message,
    )
