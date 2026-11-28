"""Integration API keys: made by the founder, shown once, scoped, revocable; never able to issue or pay."""

from app.db import SessionLocal
from app.models import ApiKey, Notification


def make_key(client, admin, scopes, name="SAXI-OS"):
    r = client.post("/api/api-keys", headers=admin, json={"name": name, "scopes": scopes})
    assert r.status_code == 201, r.text
    return r.json()


def test_key_is_shown_once_and_stored_hashed(client, admin):
    made = make_key(client, admin, ["clients:read"])
    assert made["key"].startswith("sphub_") and made["prefix"] == made["key"][:12]
    listed = client.get("/api/api-keys", headers=admin).json()
    assert "key" not in listed[0]
    with SessionLocal() as db:
        stored = db.query(ApiKey).one()
        assert stored.key_hash != made["key"] and len(stored.key_hash) == 64


def test_scopes_are_enforced_and_revocation_works(client, admin):
    made = make_key(client, admin, ["clients:read"])
    h = {"X-Api-Key": made["key"]}
    assert client.get("/api/integrations/v1/clients", headers=h).status_code == 200
    assert client.get("/api/integrations/v1/invoices", headers=h).status_code == 403
    assert client.get("/api/integrations/v1/clients", headers={"X-Api-Key": "sphub_wrong"}).status_code == 401
    assert client.get("/api/integrations/v1/clients").status_code == 401
    assert client.post(f"/api/api-keys/{made['id']}/revoke", headers=admin).status_code == 200
    assert client.get("/api/integrations/v1/clients", headers=h).status_code == 401
    assert client.post(f"/api/api-keys/{made['id']}/revoke", headers=admin).status_code == 409


def test_only_the_founder_manages_keys_and_scopes_are_a_fixed_list(client, admin, team):
    member = team[1]
    assert client.post("/api/api-keys", headers=member, json={"name": "x", "scopes": ["clients:read"]}).status_code == 403
    assert client.get("/api/api-keys", headers=member).status_code == 403
    bad = client.post("/api/api-keys", headers=admin, json={"name": "x", "scopes": ["invoices:issue"]})
    assert bad.status_code == 422


def test_a_system_can_only_save_a_draft_proposal(client, admin):
    c = client.post("/api/clients", headers=admin, json={"name": "Glow Salon", "kind": "company"}).json()
    made = make_key(client, admin, ["proposals:draft"])
    h = {"X-Api-Key": made["key"]}
    r = client.post(
        "/api/integrations/v1/proposals",
        headers=h,
        json={"client_id": c["id"], "service": "website", "title": "Website for Glow Salon", "need": "A new site"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft" and "number" not in r.json()
    with SessionLocal() as db:
        assert db.query(Notification).filter(Notification.title == "Draft proposal from SAXI-OS").count() >= 1
    # There is no route to issue, pay or change money with a key.
    pid = r.json()["id"]
    assert client.post(f"/api/proposals/{pid}/issue", headers=h).status_code == 401
    assert client.post("/api/integrations/v1/proposals/1/issue", headers=h).status_code in (404, 405)


def test_no_personal_information_leaves_through_the_api(client, admin):
    """Other systems may pass what they read to outside AI services, so the API returns no personal data."""
    from app.models import Enquiry

    c = client.post(
        "/api/clients",
        headers=admin,
        json={
            "name": "Thandi Nkosi",
            "kind": "individual",
            "email": "thandi@example.com",
            "phone": "0821234567",
            "address": "12 Oak St",
        },
    ).json()
    with SessionLocal() as db:
        db.add(
            Enquiry(
                name="Sipho Dube",
                email="sipho@example.com",
                phone="0731112222",
                organisation="Dube Plumbing",
                message="Call me on 0731112222",
                service="website",
            )
        )
        db.commit()
    made = make_key(client, admin, ["clients:read", "quotations:read", "invoices:read", "enquiries:read", "proposals:draft"])
    h = {"X-Api-Key": made["key"]}
    text = ""
    for path in ("clients", "quotations", "invoices", "enquiries"):
        r = client.get(f"/api/integrations/v1/{path}", headers=h)
        assert r.status_code == 200, r.text
        text += r.text
    r = client.post(
        "/api/integrations/v1/proposals", headers=h, json={"client_id": c["id"], "title": "Website", "service": "website"}
    )
    assert r.status_code == 201
    text += r.text
    for secret in ("Thandi", "Nkosi", "thandi@", "0821234567", "Oak St", "Sipho", "Dube", "sipho@", "0731112222"):
        assert secret not in text, secret
    assert f"Client {c['id']}" in text
