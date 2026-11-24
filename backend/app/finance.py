"""Money rules for quotations and invoices, as pure functions. All amounts are integer cents (ZAR)."""

from dataclasses import dataclass

BP = 10_000
MAX_CENTS = 2_000_000_000  # R20 million: the largest amount a single document may carry


def round_half_up(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ValueError("round_half_up expects a non-negative numerator and a positive denominator")
    return (numerator * 2 + denominator) // (denominator * 2)


def line_total(quantity: int, unit_price_cents: int) -> int:
    if quantity <= 0 or unit_price_cents < 0:
        raise ValueError("quantity must be positive and price not negative")
    return quantity * unit_price_cents


@dataclass(frozen=True)
class Totals:
    subtotal_cents: int
    vat_cents: int
    total_cents: int


def document_totals(line_totals: list[int], vat_rate_bp: int) -> Totals:
    """Subtotal of the lines, VAT on the subtotal (rounded once, half-up), and the total."""
    if not 0 <= vat_rate_bp <= BP:
        raise ValueError("vat_rate_bp must be between 0 and 10000")
    subtotal = sum(line_totals)
    vat = round_half_up(subtotal * vat_rate_bp, BP) if vat_rate_bp else 0
    total = subtotal + vat
    if total > MAX_CENTS:
        raise ValueError("Document total is too large")
    return Totals(subtotal, vat, total)


def portion_of(amount_cents: int, percent: int) -> int:
    if not 1 <= percent <= 100:
        raise ValueError("percent must be between 1 and 100")
    return round_half_up(amount_cents * percent, 100)


def excluding_vat(paid_cents: int, subtotal_cents: int, total_cents: int) -> int:
    """The part of a payment that is not VAT, in proportion to the invoice. Payouts use money excluding VAT."""
    if total_cents <= 0 or subtotal_cents == total_cents:
        return paid_cents
    return round_half_up(paid_cents * subtotal_cents, total_cents)
