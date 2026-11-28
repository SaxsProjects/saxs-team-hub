"""Statements of account (SP-SOA) and the monthly finance report, in the same layout as the other documents."""

from datetime import date

from .config import Settings, get_settings
from .payouts import format_bp, format_zar
from .pdf import _d, _Doc, _queries, _short

AGE_BUCKETS = ("Current", "1-30 days", "31-60 days", "61-90 days", "90+ days")


def age_bucket(due: date | None, as_of: date) -> int:
    days = (as_of - due).days if due else 0
    if days <= 0:
        return 0
    if days <= 30:
        return 1
    if days <= 60:
        return 2
    if days <= 90:
        return 3
    return 4


def statement_of_account_pdf(
    client, invoices, receipts, *, as_of: date, number: str | None, company: Settings | None = None
) -> bytes:
    """Open invoices with their balances and age, the payments received recently, and the total due."""
    s = company or get_settings()
    doc = _Doc("STATEMENT OF ACCOUNT", company=company, reference=number or "")
    doc.title_block(
        [
            ("Statement No", number or "Preview (numbered when sent)"),
            ("Statement date", _d(as_of)),
            ("Client", _short(client.name, 34)),
        ]
    )
    doc.parties("From", doc.from_lines(), "Statement for", doc.client_lines(client))

    ages = [0] * len(AGE_BUCKETS)
    rows = []
    for inv in invoices:
        bucket = age_bucket(inv.due_date, as_of)
        ages[bucket] += inv.balance_cents
        rows.append(
            [
                inv.number or "-",
                _d(inv.issue_date),
                _d(inv.due_date),
                format_zar(inv.total_cents),
                format_zar(inv.paid_cents + inv.credited_cents),
                format_zar(inv.balance_cents),
            ]
        )
    if rows:
        doc.section_label("Open invoices")
        doc.table_rows(
            ["Invoice", "Date", "Due", "Amount", "Paid / credited", "Balance"],
            rows,
            (30, 26, 26, 31, 31, 30),
            ("LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"),
        )
    else:
        doc.para("There are no open invoices on this account. Thank you.")

    doc.section_label("Age analysis")
    doc.table_rows(
        list(AGE_BUCKETS),
        [[format_zar(v) for v in ages]],
        (34.8,) * 5,
        ("RIGHT",) * 5,
    )

    if receipts:
        doc.section_label("Payments received (last 90 days)")
        doc.table_rows(
            ["Receipt", "Received", "Invoice", "Reference", "Amount"],
            [
                [r.number, _d(r.received_on), r.invoice.number or "-", _short(r.reference or "-", 30), format_zar(r.amount_cents)]
                for r in receipts
            ],
            (30, 28, 30, 56, 30),
            ("LEFT", "LEFT", "LEFT", "LEFT", "RIGHT"),
        )

    total = sum(ages)
    overdue = total - ages[0]
    notes = [
        (
            "How to pay",
            "Pay by EFT to the banking details on each invoice, using the invoice number as the payment reference, "
            f"and email proof of payment to {s.company_email or 'us'}.",
        )
    ]
    if overdue:
        notes.append(("Overdue", f"{format_zar(overdue)} of this balance is past its due date. Please settle it promptly."))
    if not s.vat_registered:
        notes.append(("VAT", f"{s.company_legal_name} is not a registered VAT vendor, so no VAT is charged (VAT 0%)."))
    doc.bottom(
        notes,
        [("Total invoiced (open)", format_zar(sum(i.total_cents for i in invoices)))],
        "BALANCE DUE (ZAR)",
        format_zar(total),
    )
    doc.closing("Questions about this statement", _queries(s, "statement"))
    return bytes(doc.output())


def finance_report_pdf(report: dict, *, company: Settings | None = None) -> bytes:
    """The monthly finance report: what was invoiced, received, owed and paid out, and the VAT position."""
    month: date = report["month"]
    doc = _Doc("FINANCE REPORT", company=company, reference=f"{month:%B %Y}")
    doc.title_block([("Period", f"{month:%B %Y}"), ("Prepared", _d(report["prepared_on"])), ("Currency", "ZAR")])

    doc.section_label("This month")
    m = report["totals"]
    doc.table_rows(
        ["Item", "Amount"],
        [
            ["Invoiced, excl. VAT", format_zar(m["invoiced_excl_cents"])],
            ["VAT charged", format_zar(m["vat_cents"])],
            ["Invoiced, incl. VAT", format_zar(m["invoiced_incl_cents"])],
            ["Credit notes issued", format_zar(m["credited_cents"])],
            ["Money received from clients", format_zar(m["received_cents"])],
            ["Contractor payouts paid", format_zar(m["payouts_paid_cents"])],
            ["Project costs", format_zar(m["costs_cents"])],
            ["Net cash this month (received less payouts and costs)", format_zar(m["net_cash_cents"])],
        ],
        (130, 44),
        ("LEFT", "RIGHT"),
    )

    doc.section_label("Position at month end")
    p = report["position"]
    doc.table_rows(
        ["Item", "Value"],
        [
            ["Invoices still open", f"{p['open_count']} ({format_zar(p['outstanding_cents'])})"],
            ["Of which overdue", f"{p['overdue_count']} ({format_zar(p['overdue_cents'])})"],
            ["Contractor payouts still unpaid", format_zar(p["payouts_unpaid_cents"])],
            ["Quotations awaiting an answer", str(p["quotations_open"])],
            ["Proposals awaiting an answer", str(p["proposals_open"])],
        ],
        (130, 44),
        ("LEFT", "RIGHT"),
    )

    if report["clients"]:
        doc.section_label("Invoiced per client this month")
        doc.table_rows(
            ["Client", "Invoices", "Amount incl. VAT"],
            [[_short(c["name"], 60), str(c["count"]), format_zar(c["total_cents"])] for c in report["clients"]],
            (110, 24, 40),
            ("LEFT", "RIGHT", "RIGHT"),
        )

    vat = report["vat"]
    doc.box(
        "VAT",
        [
            vat["message"],
            f"Compulsory registration threshold: {format_zar(vat['compulsory_threshold_cents'])} of taxable supplies in "
            f"12 months ({format_bp(vat['share_of_compulsory_bp'])} reached).",
        ],
    )
    doc.para(
        "Figures come from the documents issued in the Team Hub (invoices, receipts, credit notes, payout statements and "
        "recorded costs). This report is management information, not annual financial statements."
    )
    return bytes(doc.output())
