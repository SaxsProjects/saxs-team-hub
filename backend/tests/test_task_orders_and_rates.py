"""Task Orders (task-fee contractors) and the dated revenue-share rate history."""

import random
from datetime import date, timedelta

import pytest

from app.db import SessionLocal
from app.models import Person, TaskOrder
from app.payouts import Instalment, calculate_payout, calculate_payout_by_instalment
from app.services import today_local
from app.terms import task_fee_due_date

from .conftest import accept, member_login

# ---- Payout engine: one rate per instalment ------------------------------------------------------


def by_instalment(amounts_and_rates, costs=0, share=10_000, allocated=0):
    return calculate_payout_by_instalment(
        instalments=[Instalment(a, r) for a, r in amounts_and_rates],
        costs_to_date_cents=costs,
        work_share_bp=share,
        previously_allocated_cents=allocated,
    )


def test_agreement_illustration():
    # Contractor agreement Schedule: R20,000 received, R2,000 costs -> R2,700 at 15%, R3,600 at 20%.
    assert by_instalment([(2_000_000, 1500)], costs=200_000).payout_cents == 270_000
    assert by_instalment([(2_000_000, 2000)], costs=200_000).payout_cents == 360_000


def test_review_rate_applies_only_from_its_date():
    # R10,000 received before the review (15%) and R10,000 after it (20%): R1,500 + R2,000, not 20% of everything.
    calc = by_instalment([(1_000_000, 1500), (1_000_000, 2000)])
    assert calc.earned_to_date_cents == 350_000
    assert [s["rate_bp"] for s in calc.rate_segments] == [1500, 2000]


def test_costs_are_set_against_the_earliest_instalments():
    # R2,000 of costs comes off the 15% instalment first: R8,000 x 15% + R10,000 x 20% = R3,200.
    calc = by_instalment([(1_000_000, 1500), (1_000_000, 2000)], costs=200_000)
    assert calc.earned_to_date_cents == 320_000
    assert [s["net_cents"] for s in calc.rate_segments] == [800_000, 1_000_000]


def test_single_rate_matches_the_original_formula():
    rng = random.Random(20261126)  # noqa: S311 - reproducible test data, not security
    for _ in range(2_000):
        amounts = [rng.randint(0, 5_000_000) for _ in range(rng.randint(1, 6))]
        costs = rng.randint(0, 8_000_000)
        rate = rng.choice((1500, 2000))
        share = rng.randint(0, 10_000)
        allocated = rng.randint(0, 500_000)
        new = by_instalment([(a, rate) for a in amounts], costs=costs, share=share, allocated=allocated)
        old = calculate_payout(
            received_to_date_cents=sum(amounts),
            costs_to_date_cents=costs,
            rate_bp=rate,
            work_share_bp=share,
            previously_allocated_cents=allocated,
        )
        assert new.payout_cents == old.payout_cents
        assert new.earned_to_date_cents == old.earned_to_date_cents


def test_mixed_rates_stay_within_bounds_and_reconcile():
    """Across random instalment sequences, payouts are never negative, never exceed 20% of net income,
    and (with costs known up front) add up exactly to what was earned."""
    rng = random.Random(941760)  # noqa: S311 - reproducible test data, not security
    for _ in range(2_000):
        costs = rng.randint(0, 3_000_000)
        share = rng.randint(1, 10_000)
        instalments, paid = [], 0
        for _ in range(rng.randint(1, 8)):
            instalments.append((rng.randint(1, 2_000_000), rng.choice((1500, 2000))))
            calc = by_instalment(instalments, costs=costs, share=share, allocated=paid)
            assert calc.payout_cents >= 0
            paid += calc.payout_cents
        net = max(0, sum(a for a, _ in instalments) - costs)
        assert paid == calc.earned_to_date_cents
        assert paid <= -(-net * 2000 * share // 100_000_000)  # 20% ceiling, rounded up
        assert paid >= net * 1500 * share // 100_000_000  # 15% floor, rounded down


def test_task_fee_due_dates():
    fcp = date(2027, 2, 1)
    assert task_fee_due_date("standard", date(2027, 1, 10), None) == date(2027, 1, 17)
    assert task_fee_due_date("deferred", date(2027, 1, 10), None) is None  # waits for the first client payment
    assert task_fee_due_date("deferred", date(2027, 1, 10), fcp) == date(2027, 3, 3)  # 30 days after it
    assert task_fee_due_date("deferred", date(2027, 2, 1), fcp) == date(2027, 2, 8)  # accepted on/after it: 7 days


# ---- API ---------------------------------------------------------------------------------------


@pytest.fixture
def team(client, admin, sent_offer):
    person, _, token = sent_offer
    accept(client, token)
    return person, member_login(client)


def other_person(client, admin, *, fee_terms="standard"):
    other = client.post("/api/people", headers=admin, json={"full_name": "Sipho Dube", "email": "s@example.com"}).json()
    with SessionLocal() as db:
        p = db.get(Person, other["id"])
        p.status, p.fee_terms = "accepted", fee_terms
        db.commit()
    return other


def pay(client, admin, pid, cents, on, ref):
    r = client.post(
        f"/api/projects/{pid}/payments", headers=admin, json={"amount_cents": cents, "received_at": on, "reference": ref}
    )
    assert r.status_code == 201, r.text
    return r.json()["payouts"]


def test_rate_review_applies_from_its_date(client, admin, team):
    person, member = team
    pid = client.post("/api/projects", headers=admin, json={"name": "Booking app", "client_name": "Glow"}).json()["id"]
    client.put(f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": person["id"], "work_share_bp": 10_000})
    [first] = pay(client, admin, pid, 1_000_000, "2026-12-05", "EFT-1")
    assert first["amount_cents"] == 150_000  # R10,000 x 15%

    r = client.patch(
        f"/api/people/{person['id']}",
        headers=admin,
        json={"rate_bp": 2000, "rate_review_note": "6-month review signed", "rate_effective_from": "2026-12-15"},
    )
    assert r.status_code == 200, r.text
    [second] = pay(client, admin, pid, 1_000_000, "2026-12-20", "EFT-2")
    assert second["amount_cents"] == 200_000  # only the new instalment is at 20%
    assert [s["rate_bp"] for s in second["calculation"]["rate_segments"]] == [1500, 2000]

    statement = client.get(f"/api/payouts/{second['id']}/statement.pdf", headers=member)
    assert statement.status_code == 200 and statement.content.startswith(b"%PDF")

    history = client.get(f"/api/people/{person['id']}/rates", headers=admin).json()
    assert [(h["rate_bp"], h["effective_from"]) for h in history] == [(2000, "2026-12-15")]
    assert client.get("/api/me/rates", headers=member).json()[0]["review_note"] == "6-month review signed"
    dup = client.patch(
        f"/api/people/{person['id']}",
        headers=admin,
        json={"rate_bp": 1500, "rate_review_note": "x", "rate_effective_from": "2026-12-15"},
    )
    assert dup.status_code == 409


def test_backdated_review_pays_the_difference_on_the_next_instalment(client, admin, team):
    person, _ = team
    pid = client.post("/api/projects", headers=admin, json={"name": "Site", "client_name": "Client"}).json()["id"]
    client.put(f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": person["id"], "work_share_bp": 10_000})
    assert pay(client, admin, pid, 1_000_000, "2026-12-05", "EFT-1")[0]["amount_cents"] == 150_000
    # The written review was dated 1 December but recorded late.
    client.patch(
        f"/api/people/{person['id']}",
        headers=admin,
        json={"rate_bp": 2000, "rate_review_note": "Review dated 1 Dec", "rate_effective_from": "2026-12-01"},
    )
    # Next instalment: R2,000 for itself plus the R500 owed on the first one.
    assert pay(client, admin, pid, 1_000_000, "2026-12-20", "EFT-2")[0]["amount_cents"] == 250_000


def test_future_review_shows_initial_rate_until_its_date(client, admin, team):
    person, _ = team
    future = (today_local() + timedelta(days=30)).isoformat()
    no_note = client.patch(f"/api/people/{person['id']}", headers=admin, json={"rate_bp": 2000, "rate_effective_from": future})
    assert no_note.status_code == 400
    r = client.patch(
        f"/api/people/{person['id']}",
        headers=admin,
        json={"rate_bp": 2000, "rate_review_note": "Agreed in advance", "rate_effective_from": future},
    )
    assert r.json()["rate_bp"] == 1500


def create_order(client, admin, person_id, **overrides):
    body = {
        "person_id": person_id,
        "title": "Draft leave policy",
        "deliverable": "Approved leave policy in the shared drive",
        "fee_cents": 30_000,
        "due_on": "2099-01-31",
        **overrides,
    }
    r = client.post("/api/task-orders", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_task_order_lifecycle(client, admin, team):
    person, member = team
    order = create_order(client, admin, person["id"])
    assert order["number"].startswith("SP-TO-") and order["status"] == "proposed" and order["fee_terms"] == "standard"
    oid = order["id"]

    # Editable until confirmed; binding after.
    assert client.patch(f"/api/task-orders/{oid}", headers=admin, json={"fee_cents": 35_000}).json()["fee_cents"] == 35_000
    assert client.post(f"/api/me/task-orders/{oid}/submit", headers=member, json={"note": "done"}).status_code == 409
    assert client.post(f"/api/me/task-orders/{oid}/confirm", headers=member).json()["status"] == "confirmed"
    assert client.patch(f"/api/task-orders/{oid}", headers=admin, json={"fee_cents": 50_000}).status_code == 409

    r = client.post(f"/api/me/task-orders/{oid}/submit", headers=member, json={"note": "Policy is in Drive > HR"})
    assert r.json()["status"] == "submitted"
    assert r.json()["review_due_on"] == (today_local() + timedelta(days=5)).isoformat()

    # Sent back once, then accepted.
    r = client.post(f"/api/task-orders/{oid}/request-changes", headers=admin, json={"note": "Add the public holidays"})
    assert r.json()["status"] == "confirmed"
    client.post(f"/api/me/task-orders/{oid}/submit", headers=member, json={"note": "Holidays added"})
    assert client.post(f"/api/task-orders/{oid}/accept", headers=admin, json={"accepted_on": "2099-01-01"}).status_code == 400
    r = client.post(f"/api/task-orders/{oid}/accept", headers=admin, json={})
    assert r.status_code == 200, r.text
    payout = r.json()["payout"]
    assert payout["kind"] == "task_fee" and payout["amount_cents"] == 35_000 and payout["project_id"] is None
    assert payout["due_at"] == (today_local() + timedelta(days=7)).isoformat()
    assert client.post(f"/api/task-orders/{oid}/accept", headers=admin, json={}).status_code == 409

    mine = client.get("/api/me/payouts", headers=member).json()
    assert [(p["kind"], p["amount_cents"]) for p in mine] == [("task_fee", 35_000)]
    statement = client.get(f"/api/payouts/{payout['id']}/statement.pdf", headers=member)
    assert statement.status_code == 200 and statement.content.startswith(b"%PDF")
    paid = client.post(f"/api/payouts/{payout['id']}/paid", headers=admin, json={"eft_reference": "CAP-001"})
    assert paid.json()["eft_reference"] == "CAP-001"


def test_decline_cancel_and_privacy(client, admin, team):
    person, member = team
    a = create_order(client, admin, person["id"])
    assert client.post(f"/api/me/task-orders/{a['id']}/decline", headers=member, json={}).json()["status"] == "declined"
    assert client.post(f"/api/me/task-orders/{a['id']}/confirm", headers=member).status_code == 409

    b = create_order(client, admin, person["id"])
    client.post(f"/api/me/task-orders/{b['id']}/confirm", headers=member)
    r = client.post(f"/api/task-orders/{b['id']}/cancel", headers=admin, json={"note": "Client cancelled the project"})
    assert r.json()["status"] == "cancelled"

    other = other_person(client, admin)
    c = create_order(client, admin, other["id"])
    assert client.post(f"/api/me/task-orders/{c['id']}/confirm", headers=member).status_code == 404
    assert [o["id"] for o in client.get("/api/me/task-orders", headers=member).json()] == [b["id"], a["id"]]
    assert client.get("/api/task-orders", headers=member).status_code == 403

    stranger = client.post("/api/people", headers=admin, json={"full_name": "Not Yet", "email": "n@example.com"}).json()
    r = client.post(
        "/api/task-orders",
        headers=admin,
        json={"person_id": stranger["id"], "title": "Task", "deliverable": "Thing", "fee_cents": 100, "due_on": "2099-01-01"},
    )
    assert r.status_code == 400  # only people who accepted an offer


def test_review_overdue_is_flagged(client, admin, team):
    person, member = team
    oid = create_order(client, admin, person["id"])["id"]
    client.post(f"/api/me/task-orders/{oid}/confirm", headers=member)
    client.post(f"/api/me/task-orders/{oid}/submit", headers=member, json={"note": "done"})
    assert client.get("/api/task-orders?review_overdue=true", headers=admin).json() == []
    with SessionLocal() as db:
        db.get(TaskOrder, oid).review_due_on = today_local() - timedelta(days=1)
        db.commit()
    [late] = client.get("/api/task-orders?review_overdue=true", headers=admin).json()
    assert late["id"] == oid and late["review_overdue"] is True


def test_deferred_fees_wait_for_the_first_client_payment(client, admin, team):
    person, member = team
    with SessionLocal() as db:
        db.get(Person, person["id"]).fee_terms = "deferred"
        db.commit()
    oid = create_order(client, admin, person["id"])["id"]
    assert client.get(f"/api/task-orders/{oid}", headers=admin).json()["fee_terms"] == "deferred"
    client.post(f"/api/me/task-orders/{oid}/confirm", headers=member)
    client.post(f"/api/me/task-orders/{oid}/submit", headers=member, json={"note": "done"})
    payout = client.post(f"/api/task-orders/{oid}/accept", headers=admin, json={}).json()["payout"]
    assert payout["due_at"] is None  # no client income yet
    with SessionLocal() as db:  # the task was accepted ten days before the money arrived
        db.get(TaskOrder, oid).accepted_on = today_local() - timedelta(days=10)
        db.commit()

    # The first client payment arrives (on a project this person is not on): the fee becomes due 30 days later.
    other = other_person(client, admin)
    pid = client.post("/api/projects", headers=admin, json={"name": "Site", "client_name": "Client"}).json()["id"]
    client.put(f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": other["id"], "work_share_bp": 10_000})
    received = today_local()
    pay(client, admin, pid, 100_000, received.isoformat(), "EFT-1")
    [fee] = [p for p in client.get("/api/me/payouts", headers=member).json() if p["kind"] == "task_fee"]
    assert fee["due_at"] == (received + timedelta(days=30)).isoformat()

    # A task accepted after the first client payment is due 7 days after acceptance.
    oid2 = create_order(client, admin, person["id"])["id"]
    client.post(f"/api/me/task-orders/{oid2}/confirm", headers=member)
    client.post(f"/api/me/task-orders/{oid2}/submit", headers=member, json={"note": "done"})
    later = client.post(f"/api/task-orders/{oid2}/accept", headers=admin, json={}).json()["payout"]
    assert later["due_at"] == (today_local() + timedelta(days=7)).isoformat()


def test_fee_terms_can_be_set_on_a_person(client, admin, team):
    person, _ = team
    assert client.patch(f"/api/people/{person['id']}", headers=admin, json={"fee_terms": "monthly"}).status_code == 422
    r = client.patch(f"/api/people/{person['id']}", headers=admin, json={"fee_terms": "deferred"})
    assert r.status_code == 200 and r.json()["fee_terms"] == "deferred"


def test_daily_job_reminds_about_task_fees_and_late_reviews(client, admin, team):
    from app import emailer
    from app.models import Payout

    person, member = team
    done = create_order(client, admin, person["id"], title="Prepare CSD documents")["id"]
    client.post(f"/api/me/task-orders/{done}/confirm", headers=member)
    client.post(f"/api/me/task-orders/{done}/submit", headers=member, json={"note": "done"})
    payout_id = client.post(f"/api/task-orders/{done}/accept", headers=admin, json={}).json()["payout"]["id"]
    late = create_order(client, admin, person["id"], title="Monthly budget")["id"]
    client.post(f"/api/me/task-orders/{late}/confirm", headers=member)
    client.post(f"/api/me/task-orders/{late}/submit", headers=member, json={"note": "done"})
    with SessionLocal() as db:
        db.get(Payout, payout_id).due_at = today_local()
        db.get(TaskOrder, late).review_due_on = today_local() - timedelta(days=2)
        db.commit()

    r = client.post("/api/jobs/daily", headers={"X-Jobs-Token": "jobs-token-for-tests"})
    assert r.status_code == 200, r.text
    assert r.json()["payouts_due"] == 1 and r.json()["task_reviews_overdue"] == 1
    payouts_mail = next(m for m in emailer.outbox if "payout(s) due" in m.subject)
    assert "Task Order SP-TO-" in payouts_mail.text
    assert any("Monthly budget" in m.text for m in emailer.outbox if "review(s) overdue" in m.subject)


def test_review_findings_rate_edge_cases(client, admin, team):
    person, _ = team
    pid = person["id"]
    url = f"/api/people/{pid}"
    # A later 20% period, then a backdated 15% one: the rate in force today is still 20%.
    assert (
        client.patch(
            url, headers=admin, json={"rate_bp": 2000, "rate_review_note": "Review", "rate_effective_from": "2026-11-01"}
        ).status_code
        == 200
    )
    r = client.patch(
        url, headers=admin, json={"rate_bp": 1500, "rate_review_note": "Correction", "rate_effective_from": "2026-10-01"}
    )
    assert r.status_code == 400  # 15% already applied on 1 Oct, so this changes nothing
    # A no-op is refused instead of silently ignored.
    assert client.patch(url, headers=admin, json={"rate_bp": 2000, "rate_review_note": "again"}).status_code == 400

    # A change dated ahead can be withdrawn; one already in force cannot.
    future = (today_local() + timedelta(days=20)).isoformat()
    client.patch(url, headers=admin, json={"rate_bp": 1500, "rate_review_note": "Planned", "rate_effective_from": future})
    periods = client.get(f"{url}/rates", headers=admin).json()
    started, planned = periods[0], periods[-1]
    assert client.delete(f"{url}/rates/{started['id']}", headers=admin).status_code == 409
    assert client.delete(f"{url}/rates/{planned['id']}", headers=admin).status_code == 204
    assert [p["effective_from"] for p in client.get(f"{url}/rates", headers=admin).json()] == ["2026-11-01"]
    assert client.get(url, headers=admin).json()["rate_bp"] == 2000


def test_person_with_task_orders_cannot_be_erased(client, admin, team):
    person, _ = team
    create_order(client, admin, person["id"])
    assert client.delete(f"/api/people/{person['id']}", headers=admin).status_code == 409


def test_backdated_first_payment_moves_deferred_due_dates(client, admin, team):
    person, member = team
    with SessionLocal() as db:
        db.get(Person, person["id"]).fee_terms = "deferred"
        db.commit()
    oid = create_order(client, admin, person["id"])["id"]
    client.post(f"/api/me/task-orders/{oid}/confirm", headers=member)
    client.post(f"/api/me/task-orders/{oid}/submit", headers=member, json={"note": "done"})
    client.post(f"/api/task-orders/{oid}/accept", headers=admin, json={})
    other = other_person(client, admin)
    project = client.post("/api/projects", headers=admin, json={"name": "Site", "client_name": "Client"}).json()["id"]
    client.put(f"/api/projects/{project}/contributors", headers=admin, json={"person_id": other["id"], "work_share_bp": 10_000})
    today = today_local()
    with SessionLocal() as db:  # accepted 10 days ago, before any money came in
        db.get(TaskOrder, oid).accepted_on = today - timedelta(days=10)
        db.commit()
    pay(client, admin, project, 100_000, today.isoformat(), "EFT-1")
    assert client.get("/api/me/payouts", headers=member).json()[0]["due_at"] == (today + timedelta(days=30)).isoformat()
    # A payment received 20 days ago is recorded late: it is now the First Client Payment, and the
    # task (accepted 10 days ago) was accepted after it, so the fee is due 7 days after acceptance.
    pay(client, admin, project, 100_000, (today - timedelta(days=20)).isoformat(), "EFT-0")
    assert client.get("/api/me/payouts", headers=member).json()[0]["due_at"] == (today - timedelta(days=3)).isoformat()
