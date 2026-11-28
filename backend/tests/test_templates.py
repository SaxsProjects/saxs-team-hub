"""The company template library: founder only, PDFs only, versions kept, archived not deleted, all audited."""

from app.db import SessionLocal
from app.models import AuditLog

from .conftest import PDF

PDF_V2 = PDF.replace(b"1.4", b"1.7")


def upload(client, admin, name="Offer letter", category="offer", content=PDF, description="Standard offer letter"):
    return client.post(
        "/api/templates",
        headers=admin,
        data={"name": name, "category": category, "description": description},
        files={"file": ("offer-letter.pdf", content, "application/pdf")},
    )


def test_founder_uploads_lists_and_views_a_template(client, admin):
    r = upload(client, admin)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["name"] == "Offer letter" and t["category"] == "offer" and not t["archived"]
    assert t["current"]["version"] == 1 and t["current"]["filename"] == "offer-letter.pdf"
    assert [x["id"] for x in client.get("/api/templates", headers=admin).json()] == [t["id"]]

    pdf = client.get(f"/api/templates/{t['id']}/pdf", headers=admin)
    assert pdf.status_code == 200 and pdf.content == PDF
    assert pdf.headers["content-type"] == "application/pdf"
    assert 'filename="Offer_letter_v1.pdf"' in pdf.headers["content-disposition"]


def test_only_pdfs_and_unique_names(client, admin):
    assert upload(client, admin, content=b"MZ\x90\x00 not a pdf").status_code == 400
    assert upload(client, admin, category="anything").status_code == 422
    assert upload(client, admin).status_code == 201
    assert upload(client, admin, name="offer LETTER").status_code == 409  # names are unique, ignoring case


def test_new_versions_keep_the_old_ones(client, admin):
    t = upload(client, admin).json()
    r = client.post(
        f"/api/templates/{t['id']}/versions",
        headers=admin,
        data={"note": "New clause 4"},
        files={"file": ("offer-letter-2.pdf", PDF_V2, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert [v["version"] for v in body["versions"]] == [2, 1]
    assert body["current"]["note"] == "New clause 4"
    assert client.get(f"/api/templates/{t['id']}/pdf", headers=admin).content == PDF_V2
    assert client.get(f"/api/templates/{t['id']}/pdf?version=1", headers=admin).content == PDF
    assert client.get(f"/api/templates/{t['id']}/pdf?version=9", headers=admin).status_code == 404


def test_edit_archive_and_restore(client, admin):
    t = upload(client, admin).json()
    upload(client, admin, name="Letterhead", category="letterhead")
    r = client.put(f"/api/templates/{t['id']}", headers=admin, json={"name": "Letterhead", "category": "offer"})
    assert r.status_code == 409
    r = client.put(f"/api/templates/{t['id']}", headers=admin, json={"name": "Offer letter 2026", "category": "contract"})
    assert r.status_code == 200 and r.json()["category"] == "contract"

    assert client.post(f"/api/templates/{t['id']}/archive", headers=admin).json()["archived"]
    assert [x["name"] for x in client.get("/api/templates", headers=admin).json()] == ["Letterhead"]
    assert len(client.get("/api/templates?include_archived=true", headers=admin).json()) == 2
    # Archived templates stay readable, but take no new versions until restored.
    assert client.get(f"/api/templates/{t['id']}/pdf", headers=admin).status_code == 200
    files = {"file": ("x.pdf", PDF_V2, "application/pdf")}
    assert client.post(f"/api/templates/{t['id']}/versions", headers=admin, files=files).status_code == 409
    assert not client.post(f"/api/templates/{t['id']}/restore", headers=admin).json()["archived"]

    with SessionLocal() as db:
        actions = [a.action for a in db.query(AuditLog).filter(AuditLog.entity == "company_template").order_by(AuditLog.id)]
    assert actions == ["template.create", "template.create", "template.edit", "template.archive", "template.restore"]


def test_members_and_strangers_cannot_see_templates(client, admin, team):
    t = upload(client, admin).json()
    _, member = team
    for method, path in (
        ("get", "/api/templates"),
        ("get", f"/api/templates/{t['id']}/pdf"),
        ("post", f"/api/templates/{t['id']}/archive"),
    ):
        assert getattr(client, method)(path, headers=member).status_code == 403
        assert getattr(client, method)(path).status_code == 401
    r = client.post("/api/templates", headers=member, data={"name": "x y", "category": "offer"}, files={"file": ("a.pdf", PDF)})
    assert r.status_code == 403
