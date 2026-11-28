"""Outgoing email: Resend's HTTPS API when RESEND_API_KEY is set, otherwise SMTP (Zoho Mail).

Render's free plan blocks outgoing SMTP ports, so production sends over HTTPS (port 443) through
Resend, from an address on the company domain verified there (SMTP_FROM, e.g. admin@).
Over SMTP, Zoho only accepts mail whose From address is the mailbox you log in with (or a
verified alias), so From defaults to SMTP_USER.

Without email settings (development/tests) messages are kept in `outbox` and
logged instead of sent.
"""

import base64
import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .config import get_settings

log = logging.getLogger("teamhub.email")


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    reply_to: str | None = None
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)


# Messages "sent" while SMTP is not configured. Tests read this.
outbox: list[OutgoingEmail] = []


def _build(msg: OutgoingEmail) -> EmailMessage:
    settings = get_settings()
    em = EmailMessage()
    sender = settings.email_sender
    em["From"] = formataddr((settings.smtp_from_name, sender))
    em["To"] = msg.to
    em["Subject"] = _clean_header(msg.subject)
    em["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    if msg.reply_to:
        em["Reply-To"] = msg.reply_to
    em.set_content(msg.text)
    for filename, data, content_type in msg.attachments:
        maintype, _, subtype = content_type.partition("/")
        em.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
    return em


def _clean_header(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")


def _resend_payload(msg: OutgoingEmail) -> dict:
    settings = get_settings()
    payload = {
        "from": formataddr((settings.smtp_from_name, settings.email_sender)),
        "to": [msg.to],
        "subject": _clean_header(msg.subject),
        "text": msg.text,
    }
    if msg.reply_to:
        payload["reply_to"] = msg.reply_to
    if msg.attachments:
        payload["attachments"] = [
            {"filename": filename, "content": base64.b64encode(data).decode("ascii"), "content_type": content_type}
            for filename, data, content_type in msg.attachments
        ]
    return payload


def _send_resend(msg: OutgoingEmail) -> bool:
    settings = get_settings()
    request = urllib.request.Request(  # noqa: S310 - fixed https URL from settings
        settings.resend_api_url,
        data=json.dumps(_resend_payload(msg)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.resend_api_key.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "saxs-team-hub/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", "replace")
        log.error("Email to %s refused by Resend (HTTP %s): %s", msg.to, exc.code, detail)
    except (urllib.error.URLError, OSError) as exc:
        log.error("Email to %s failed: %s", msg.to, exc)
    return False


def send_email(msg: OutgoingEmail) -> bool:
    """Send one email. Returns False (and logs) on failure instead of raising."""
    settings = get_settings()
    if settings.resend_configured:
        return _send_resend(msg)
    if not settings.smtp_configured:
        outbox.append(msg)
        log.info("Email not sent (email not configured): to=%s subject=%s", msg.to, msg.subject)
        return True
    try:
        context = ssl.create_default_context()
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20) as smtp:
                smtp.login(settings.smtp_user, settings.smtp_pass)
                smtp.send_message(_build(msg))
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.starttls(context=context)
                smtp.login(settings.smtp_user, settings.smtp_pass)
                smtp.send_message(_build(msg))
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.error("Email to %s failed: %s", msg.to, exc)
        return False


# Founder emails that can be switched off in Settings. Anything else (e.g. sign-in alerts) always goes.
NOTIFY_KINDS = ("offers", "reviews", "payouts", "invoices")


def notify_enabled(db, kind: str) -> bool:
    """True unless the founder switched this kind of email off."""
    from sqlalchemy import select

    from .models import User

    prefs = db.scalar(select(User.notify_prefs).where(User.role == "admin").order_by(User.id).limit(1))
    return not (prefs and prefs.get(kind) is False)


DISCORD_MARKDOWN = set(chr(92) + "*_~`|>[]()#-:<@")


def post_to_discord(title: str, link: str | None = None) -> None:
    """Post a one-line alert to the founder's Discord channel, if a webhook is set. Runs in the background and
    never raises. Only the title and a link go to Discord: details stay in the Team Hub. Markdown in the title
    is escaped and link previews and mentions are switched off, so text from outside can't format or ping."""
    url = get_settings().discord_webhook_url.strip()
    if not url.startswith("https://discord.com/api/webhooks/"):
        return
    import json
    import threading
    import urllib.request

    from .services import link as hub_link

    safe = "".join(chr(92) + ch if ch in DISCORD_MARKDOWN else ch for ch in title[:300].replace(chr(10), " "))
    content = safe + (chr(10) + hub_link(link) if link else "")

    def send() -> None:
        try:
            body = json.dumps({"content": content, "allowed_mentions": {"parse": []}, "flags": 4}).encode()
            headers = {"Content-Type": "application/json", "User-Agent": "SaxsTeamHub"}
            req = urllib.request.Request(url, data=body, headers=headers)  # noqa: S310 - url checked to be a discord.com https webhook above
            urllib.request.urlopen(req, timeout=8).close()  # noqa: S310
        except Exception:
            log.warning("Discord alert failed: %s", title)

    threading.Thread(target=send, daemon=True).start()


def notify_admin(
    subject: str, text: str, *, kind: str | None = None, db=None, link: str | None = None, discord: str | None = None
) -> None:
    """Email the founder, put the same message in the notification bell, and post `discord` (or the subject) to
    Discord if a webhook is set. Pass a `discord` title without outside text (names, messages) where there is any.

    With `db`, the bell entry is saved with the caller's transaction (the caller commits); without it (in
    background tasks) it is saved on its own. The email switches in Settings only affect the email."""
    from .notifications import notify_admins, notify_detached

    try:
        if db is not None:
            notify_admins(db, kind or "system", subject, text, link)
        else:
            notify_detached(kind or "system", subject, text, link)
    except Exception:  # the bell must never break the action that triggered it
        log.exception("Could not save the in-app notification: %s", subject)
    settings = get_settings()
    if kind and db is not None and not notify_enabled(db, kind):
        log.info("Admin notification switched off (%s): %s", kind, subject)
        return
    post_to_discord(discord or subject, link)
    if settings.admin_notify_email:
        send_email(OutgoingEmail(to=settings.admin_notify_email, subject=subject, text=text))
    else:
        log.warning("ADMIN_NOTIFY_EMAIL not set; admin notification dropped: %s", subject)
