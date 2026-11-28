"""Saxs Assistant: the Team Hub's own helper. It reads the hub's records and says what needs doing next.

It is rule-based (no outside AI service, no cost, nothing leaves the server): every suggestion comes from a
record in the database or from the company's compliance calendar, and links to the screen where it is done.
Routine follow-ups (payment reminders, statements, the monthly report) run on their own; the founder decides
everything that commits the company (issuing, paying, signing).
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .client_finance import autopilot_enabled
from .models import Invoice, Offer, OnboardingItem, Payout, Proposal, Quotation, TaskOrder, User
from .payouts import format_zar
from .services import local_tz, today_local
from .vat import vat_position

LOOKAHEAD = timedelta(days=75)


@dataclass
class Suggestion:
    id: str
    priority: str  # high | normal | info
    title: str
    detail: str
    link: str
    action: str


@dataclass
class Deadline:
    on: date
    title: str
    detail: str


# The company's recurring obligations (SaxsProjects (Pty) Ltd, incorporated 24 Nov 2026, year end 31 Dec).
# (month, day, title, detail, first year it applies)
CALENDAR = (
    (6, 30, "Provisional tax (IRP6), first period", "File on eFiling and pay any tax due for the first half of the year.", 2027),
    (12, 31, "Provisional tax (IRP6), second period", "File on eFiling (a nil return if there is no taxable income yet).", 2026),
    (11, 24, "CIPC annual return", "Due within 30 business days of the incorporation anniversary (24 November).", 2027),
    (6, 30, "Annual financial statements", "Approve the year's financial statements within 6 months of year end (s30).", 2027),
    (12, 31, "Company income tax return (ITR14)", "Due within 12 months of the financial year end.", 2027),
    (6, 30, "PAIA annual report to the Information Regulator", "Submit between 1 April and 30 June.", 2027),
    (11, 22, "B-BBEE affidavit renewal", "The EME affidavit is valid for 12 months; sign a new one.", 2027),
)


def upcoming_deadlines(today: date) -> list[Deadline]:
    out = []
    for month, day, title, detail, first in CALENDAR:
        for year in (today.year, today.year + 1):
            on = date(year, month, day)
            if year >= first and today <= on <= today + LOOKAHEAD:
                out.append(Deadline(on, title, detail))
    return sorted(out, key=lambda d: d.on)


def _count(db: Session, model, *where) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def founder_suggestions(db: Session, today: date) -> list[Suggestion]:
    out: list[Suggestion] = []
    add = out.append

    vat = vat_position(db, today)
    if vat.status in ("must_register", "approaching"):
        add(
            Suggestion(
                "vat",
                "high" if vat.status == "must_register" else "normal",
                "VAT registration",
                vat.message,
                "/finance",
                "Review",
            )
        )

    requested = _count(db, Payout, Payout.paid_at.is_(None), Payout.payment_requested_at.is_not(None))
    if requested:
        add(
            Suggestion(
                "payout-requests",
                "high",
                f"{_plural(requested, 'payment request')} from the team",
                "Pay by EFT from the business account, then mark each as paid with its EFT reference.",
                "/payouts",
                "Open payouts",
            )
        )
    due = db.scalars(select(Payout).where(Payout.paid_at.is_(None), Payout.due_at <= today)).all()
    if due:
        add(
            Suggestion(
                "payouts-due",
                "high",
                f"{_plural(len(due), 'payout')} due ({format_zar(sum(p.amount_cents for p in due))})",
                "These contractor payouts have reached their due date.",
                "/payouts",
                "Open payouts",
            )
        )

    reviews = db.scalars(select(TaskOrder).where(TaskOrder.status == "submitted")).all()
    if reviews:
        late = sum(1 for t in reviews if t.review_due_on and t.review_due_on < today)
        add(
            Suggestion(
                "reviews",
                "high" if late else "normal",
                f"{_plural(len(reviews), 'task')} waiting for your review",
                (f"{late} past the review date. " if late else "") + "Accept the work or say what remains.",
                "/task-orders",
                "Review",
            )
        )

    open_invoices = [
        i for i in db.scalars(select(Invoice).where(Invoice.status.in_(("issued", "part_paid")))) if i.balance_cents > 0
    ]
    overdue = [i for i in open_invoices if i.due_date and i.due_date < today]
    if overdue:
        reminders = autopilot_enabled(db, "client_reminders")
        add(
            Suggestion(
                "overdue",
                "high",
                f"{_plural(len(overdue), 'invoice')} overdue ({format_zar(sum(i.balance_cents for i in overdue))})",
                "Payment reminders are being emailed automatically."
                if reminders
                else "Automatic reminders are off: follow up with the clients or switch them on in Settings.",
                "/finance/invoices",
                "Open invoices",
            )
        )
    finals = [i for i in overdue if i.reminder_stage >= 4]
    if finals:
        add(
            Suggestion(
                "final-notices",
                "normal",
                f"{_plural(len(finals), 'client')} received a final notice",
                "Decide whether to send a letter of demand (Templates) or agree a payment plan.",
                "/templates",
                "Letter of demand",
            )
        )

    drafts = _count(db, Invoice, Invoice.status == "draft")
    if drafts:
        add(
            Suggestion(
                "draft-invoices",
                "normal",
                f"{_plural(drafts, 'draft invoice')}",
                "Issue them so the client can pay.",
                "/finance/invoices",
                "Open",
            )
        )

    stale = today - timedelta(days=7)
    quotes = _count(db, Quotation, Quotation.status == "issued", Quotation.issue_date <= stale)
    if quotes:
        add(
            Suggestion(
                "quotes",
                "normal",
                f"{_plural(quotes, 'quotation')} without an answer for a week",
                "Follow up with the client, or mark them accepted or declined.",
                "/finance/quotations",
                "Open",
            )
        )
    proposals = _count(db, Proposal, Proposal.status == "issued", Proposal.issue_date <= stale)
    if proposals:
        add(
            Suggestion(
                "proposals",
                "normal",
                f"{_plural(proposals, 'proposal')} without an answer for a week",
                "Follow up with the client.",
                "/proposals",
                "Open",
            )
        )
    unpriced = _count(db, Proposal, Proposal.status == "draft", Proposal.subtotal_cents == 0)
    if unpriced:
        add(
            Suggestion(
                "unpriced",
                "info",
                f"{_plural(unpriced, 'draft proposal')} still to price",
                "Set the prices, then issue.",
                "/proposals",
                "Open",
            )
        )

    offers = _count(db, Offer, Offer.status.in_(("sent", "viewed")), Offer.deadline <= today + timedelta(days=2))
    if offers:
        add(
            Suggestion(
                "offers",
                "normal",
                f"{_plural(offers, 'offer')} close within 2 days",
                "The candidate has not answered yet.",
                "/team",
                "Open",
            )
        )

    for d in upcoming_deadlines(today):
        days = (d.on - today).days
        add(
            Suggestion(
                f"deadline-{d.on.isoformat()}-{d.title[:12]}",
                "high" if days <= 14 else "info",
                f"{d.title}: {d.on:%d %b %Y}",
                d.detail + (f" ({days} days left)" if days else " (today)"),
                "/settings",
                "Noted",
            )
        )
    return out


def member_suggestions(db: Session, user: User, today: date) -> list[Suggestion]:
    person = user.person
    if person is None:
        return []
    out: list[Suggestion] = []
    confirm = _count(db, TaskOrder, TaskOrder.person_id == person.id, TaskOrder.status == "proposed")
    if confirm:
        out.append(
            Suggestion(
                "confirm",
                "high",
                f"{_plural(confirm, 'Task Order')} to confirm",
                "Accept or decline the new work.",
                "/my/task-orders",
                "Open",
            )
        )
    working = db.scalars(select(TaskOrder).where(TaskOrder.person_id == person.id, TaskOrder.status == "confirmed")).all()
    for t in working:
        if t.due_on and t.due_on <= today + timedelta(days=3):
            out.append(
                Suggestion(
                    f"due-{t.id}",
                    "high" if t.due_on < today else "normal",
                    f"{t.number} is due {t.due_on:%d %b}",
                    f"{t.title}. Submit it when it is ready.",
                    "/my/task-orders",
                    "Open",
                )
            )
    payable = _count(
        db,
        Payout,
        Payout.person_id == person.id,
        Payout.paid_at.is_(None),
        Payout.due_at <= today,
        Payout.payment_requested_at.is_(None),
    )
    if payable:
        out.append(
            Suggestion(
                "request", "normal", "A payout is ready to request", "Ask for payment of what is due.", "/my/payouts", "Open"
            )
        )
    onboarding = _count(db, OnboardingItem, OnboardingItem.person_id == person.id, OnboardingItem.done.is_(False))
    if onboarding:
        out.append(
            Suggestion(
                "onboarding", "info", "Finish your onboarding", f"{_plural(onboarding, 'step')} left.", "/my/onboarding", "Open"
            )
        )
    if user.avatar_updated_at is None:
        out.append(
            Suggestion(
                "photo", "info", "Add your profile picture", "The company logo is shown until you do.", "/settings", "Settings"
            )
        )
    return out


def briefing(db: Session, user: User) -> dict:
    today = today_local()
    hour = datetime.now(local_tz()).hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    name = (user.person.full_name.split()[0] if user.person and user.person.full_name else "") if user.role != "admin" else ""
    if user.role == "admin":
        items = founder_suggestions(db, today)
        autopilot = {
            "client_reminders": autopilot_enabled(db, "client_reminders"),
            "client_statements": autopilot_enabled(db, "client_statements"),
            "monthly_report": True,
        }
    else:
        items = member_suggestions(db, user, today)
        autopilot = {}
    order = {"high": 0, "normal": 1, "info": 2}
    items.sort(key=lambda s: order[s.priority])
    high = sum(1 for s in items if s.priority == "high")
    summary = (
        "Nothing needs you right now."
        if not items
        else f"{_plural(high, 'thing')} need{'s' if high == 1 else ''} you today."
        if high
        else "No urgent items; a few things to look at."
    )
    return {
        "greeting": f"Good {part}{', ' + name if name else ''}.",
        "summary": summary,
        "today": today,
        "items": [asdict(s) for s in items],
        "autopilot": autopilot,
    }
