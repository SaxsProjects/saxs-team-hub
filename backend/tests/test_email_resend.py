"""Email over Resend's HTTPS API (Render's free plan blocks SMTP ports)."""

import base64
import io
import json
import urllib.error

import pytest

from app import emailer
from app.config import Settings, get_settings
from app.emailer import OutgoingEmail, send_email


@pytest.fixture
def resend(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "smtp_from", "admin@saxsprojects.co.za")
    monkeypatch.setattr(settings, "smtp_from_name", "SaxsProjects Team Hub")
    sent = []

    class Reply:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        sent.append(request)
        return Reply()

    monkeypatch.setattr(emailer.urllib.request, "urlopen", fake_urlopen)
    return sent


def test_sends_over_https_with_attachments(resend):
    before = len(emailer.outbox)
    ok = send_email(
        OutgoingEmail(
            to="pfano@saxsprojects.co.za",
            subject="Offer\r\nBcc: evil@example.com",
            text="Hello",
            reply_to="phathutshedzo@saxsprojects.co.za",
            attachments=[("record.pdf", b"%PDF-1.7 test", "application/pdf")],
        )
    )
    assert ok and len(emailer.outbox) == before
    [request] = resend
    assert request.full_url == "https://api.resend.com/emails"
    assert request.get_header("Authorization") == "Bearer re_test_key"
    body = json.loads(request.data)
    assert body["from"] == "SaxsProjects Team Hub <admin@saxsprojects.co.za>"
    assert body["to"] == ["pfano@saxsprojects.co.za"]
    assert "\n" not in body["subject"] and "\r" not in body["subject"]
    assert body["reply_to"] == "phathutshedzo@saxsprojects.co.za"
    [att] = body["attachments"]
    assert att["filename"] == "record.pdf" and base64.b64decode(att["content"]) == b"%PDF-1.7 test"


def test_refusal_is_logged_not_raised(resend, monkeypatch, caplog):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"message":"domain not verified"}'))

    monkeypatch.setattr(emailer.urllib.request, "urlopen", refuse)
    assert send_email(OutgoingEmail(to="a@example.com", subject="s", text="t")) is False
    assert "domain not verified" in caplog.text and "re_test_key" not in caplog.text


def test_production_accepts_resend_instead_of_smtp():
    base = dict(
        environment="production",
        secret_key="x" * 40,
        field_encryption_key="k",
        database_url="postgresql://u:p@h/db?sslmode=require",
        admin_notify_email="admin@saxsprojects.co.za",
        signature_image_base64="aGk=",
        signatory_name="P M",
    )
    Settings(**base, resend_api_key="re_x", smtp_from="admin@saxsprojects.co.za").check_production_ready()
    with pytest.raises(RuntimeError, match="Email must be configured"):
        Settings(**base, resend_api_key="re_x").check_production_ready()
    with pytest.raises(RuntimeError, match="Email must be configured"):
        Settings(**base).check_production_ready()
