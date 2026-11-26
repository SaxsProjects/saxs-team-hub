"""Contractor payout rules (README §4.5), as pure functions so they are easy to test.

    net_project_income = client_amount_received - direct_project_costs
    contributor_payout = net_project_income x contributor_rate x contributor_work_share

Projects are often paid in instalments, so each client payment triggers a payout
for the amount the contributor has *newly* earned:

    earned_to_date = max(0, received_to_date - costs_to_date) x rate x share
    payout         = max(0, earned_to_date - already_allocated)

This means costs recorded later reduce later payouts, nothing is ever clawed back,
and the total paid never exceeds the contributor's share of net income.
All amounts are integer cents; rate and share are basis points (1% = 100).

Rate changes (contractor agreement clause 5: 15% initially, 20% "from the date" a written review
confirms it). Each instalment is shared at the rate in force on the date it was received, so income
received before a review stays at 15%. Direct costs are set against the earliest instalments first:

    net slice of instalment j = max(0, R_j - C) - max(0, R_(j-1) - C)
    earned_to_date            = sum(slice_j x rate_j) x share, rounded once

where R_j is the total received up to and including instalment j and C is all costs to date.
With one rate throughout this is exactly max(0, R - C) x rate x share.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

BP = 10_000


def _round_half_up(numerator: int, denominator: int) -> int:
    return (numerator * 2 + denominator) // (denominator * 2)


@dataclass(frozen=True)
class PayoutCalculation:
    received_to_date_cents: int
    costs_to_date_cents: int
    net_income_cents: int
    rate_bp: int
    work_share_bp: int
    earned_to_date_cents: int
    previously_allocated_cents: int
    payout_cents: int
    # One entry per instalment when the project was paid at more than one rate.
    rate_segments: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def earned(net_income_cents: int, rate_bp: int, work_share_bp: int) -> int:
    if net_income_cents <= 0:
        return 0
    return _round_half_up(net_income_cents * rate_bp * work_share_bp, BP * BP)


def calculate_payout(
    *, received_to_date_cents: int, costs_to_date_cents: int, rate_bp: int, work_share_bp: int, previously_allocated_cents: int
) -> PayoutCalculation:
    for name, value in (("rate_bp", rate_bp), ("work_share_bp", work_share_bp)):
        if not 0 <= value <= BP:
            raise ValueError(f"{name} must be between 0 and {BP}")
    if received_to_date_cents < 0 or costs_to_date_cents < 0 or previously_allocated_cents < 0:
        raise ValueError("amounts cannot be negative")
    net = received_to_date_cents - costs_to_date_cents
    earned_to_date = earned(net, rate_bp, work_share_bp)
    return PayoutCalculation(
        received_to_date_cents=received_to_date_cents,
        costs_to_date_cents=costs_to_date_cents,
        net_income_cents=net,
        rate_bp=rate_bp,
        work_share_bp=work_share_bp,
        earned_to_date_cents=earned_to_date,
        previously_allocated_cents=previously_allocated_cents,
        payout_cents=max(0, earned_to_date - previously_allocated_cents),
    )


@dataclass(frozen=True)
class Instalment:
    amount_cents: int
    rate_bp: int
    label: str = ""  # e.g. the payment date, shown on the statement


def calculate_payout_by_instalment(
    *,
    instalments: Sequence[Instalment],
    costs_to_date_cents: int,
    work_share_bp: int,
    previously_allocated_cents: int,
) -> PayoutCalculation:
    """Like `calculate_payout`, but each instalment is shared at its own rate. `instalments` are in date order."""
    if not instalments:
        raise ValueError("at least one instalment is needed")
    if not 0 <= work_share_bp <= BP:
        raise ValueError(f"work_share_bp must be between 0 and {BP}")
    if costs_to_date_cents < 0 or previously_allocated_cents < 0:
        raise ValueError("amounts cannot be negative")
    received = 0
    numerator = 0  # sum of slice x rate, kept exact until the single rounding step
    segments = []
    for inst in instalments:
        if inst.amount_cents < 0:
            raise ValueError("amounts cannot be negative")
        if not 0 <= inst.rate_bp <= BP:
            raise ValueError(f"rate_bp must be between 0 and {BP}")
        before = max(0, received - costs_to_date_cents)
        received += inst.amount_cents
        net_slice = max(0, received - costs_to_date_cents) - before
        numerator += net_slice * inst.rate_bp
        segments.append({"label": inst.label, "net_cents": net_slice, "rate_bp": inst.rate_bp})
    earned_to_date = _round_half_up(numerator * work_share_bp, BP * BP)
    rates = {s["rate_bp"] for s in segments if s["net_cents"]} or {instalments[-1].rate_bp}
    return PayoutCalculation(
        received_to_date_cents=received,
        costs_to_date_cents=costs_to_date_cents,
        net_income_cents=received - costs_to_date_cents,
        rate_bp=instalments[-1].rate_bp,
        work_share_bp=work_share_bp,
        earned_to_date_cents=earned_to_date,
        previously_allocated_cents=previously_allocated_cents,
        payout_cents=max(0, earned_to_date - previously_allocated_cents),
        rate_segments=segments if len(rates) > 1 else [],
    )


def format_zar(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}R{cents // 100:,}.{cents % 100:02d}"


def format_bp(bp: int) -> str:
    return f"{bp / 100:g}%"
