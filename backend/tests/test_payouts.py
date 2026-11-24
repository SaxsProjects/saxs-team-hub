import pytest

from app.payouts import calculate_payout, earned, format_zar


def test_readme_example():
    # R10,000 received, R1,000 costs, 15% rate, 50% share -> R675.00
    calc = calculate_payout(
        received_to_date_cents=1_000_000,
        costs_to_date_cents=100_000,
        rate_bp=1500,
        work_share_bp=5000,
        previously_allocated_cents=0,
    )
    assert calc.net_income_cents == 900_000
    assert calc.payout_cents == 67_500


def test_instalments_pay_only_newly_earned_amount():
    first = calculate_payout(
        received_to_date_cents=500_000, costs_to_date_cents=0, rate_bp=2000, work_share_bp=10_000, previously_allocated_cents=0
    )
    second = calculate_payout(
        received_to_date_cents=1_000_000,
        costs_to_date_cents=0,
        rate_bp=2000,
        work_share_bp=10_000,
        previously_allocated_cents=first.payout_cents,
    )
    assert first.payout_cents == 100_000
    assert second.payout_cents == 100_000
    assert first.payout_cents + second.payout_cents == earned(1_000_000, 2000, 10_000)


def test_costs_above_income_pay_nothing():
    calc = calculate_payout(
        received_to_date_cents=100_000,
        costs_to_date_cents=150_000,
        rate_bp=1500,
        work_share_bp=10_000,
        previously_allocated_cents=0,
    )
    assert calc.net_income_cents == -50_000
    assert calc.payout_cents == 0


def test_late_costs_never_claw_back():
    calc = calculate_payout(
        received_to_date_cents=200_000,
        costs_to_date_cents=150_000,
        rate_bp=1500,
        work_share_bp=10_000,
        previously_allocated_cents=20_000,
    )
    assert calc.earned_to_date_cents == 7_500
    assert calc.payout_cents == 0


def test_rounds_half_up_to_the_cent():
    # 1 cent x 15% x 50% = 0.075c -> 0; 7 cents x 15% x 50% = 0.525c -> 1c
    assert earned(1, 1500, 5000) == 0
    assert earned(7, 1500, 5000) == 1


def test_rejects_invalid_rates():
    with pytest.raises(ValueError):
        calculate_payout(
            received_to_date_cents=1, costs_to_date_cents=0, rate_bp=10_001, work_share_bp=1, previously_allocated_cents=0
        )


def test_format_zar():
    assert format_zar(123_456_78) == "R123,456.78"
    assert format_zar(5) == "R0.05"
