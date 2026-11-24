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
"""

from dataclasses import asdict, dataclass

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


def format_zar(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}R{cents // 100:,}.{cents % 100:02d}"


def format_bp(bp: int) -> str:
    return f"{bp / 100:g}%"
