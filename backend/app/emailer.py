"""Outgoing email over SMTP (Zoho Mail by default).

Zoho only accepts mail whose From address is the mailbox you log in with (or a
verified alias), so From defaults to SMTP_USER.

Without SMTP settings (development/tests) messages are kept in `outbox` and
logged instead of sent.
"""

import logging
import smtplib
import ssl
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
    sender = settings.smtp_from or settings.smtp_user
    em["From"] = formataddr((settings.smtp_from_name, sender))
    em["To"] = msg.to
    em["Subject"] = msg.subject.replace("\r", " ").replace("\n", " ")
    em["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    if msg.reply_to:
        em["Reply-To"] = msg.reply_to
    em.set_content(msg.text)
    for filename, data, content_type in msg.attachments:
        maintype, _, subtype = content_type.partition("/")
        em.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
    return em


def send_email(msg: OutgoingEmail) -> bool:
    """Send one email. Returns False (and logs) on failure instead of raising."""
    settings = get_settings()
    if not settings.smtp_configured:
        outbox.append(msg)
        log.info("Email not sent (SMTP not configured): to=%s subject=%s", msg.to, msg.subject)
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


def notify_admin(subject: str, text: str) -> None:
    settings = get_settings()
    if settings.admin_notify_email:
        send_email(OutgoingEmail(to=settings.admin_notify_email, subject=subject, text=text))
    else:
        log.warning("ADMIN_NOTIFY_EMAIL not set; admin notification dropped: %s", subject)
