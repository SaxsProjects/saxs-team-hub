"""Command-line helpers.

python -m app.cli generate-keys            # print new SECRET_KEY / FIELD_ENCRYPTION_KEY / JOBS_TOKEN
python -m app.cli create-admin EMAIL       # create the founder's admin account (asks for a password)
python -m app.cli daily-jobs               # expire offers, payout reminders, POPIA retention
python -m app.cli check-email [TO]         # log in to SMTP (Zoho) and send a test email
"""

import argparse
import getpass
import os
import secrets
import sys

from cryptography.fernet import Fernet
from sqlalchemy import select


def generate_keys() -> None:
    print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"FIELD_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    print(f"JOBS_TOKEN={secrets.token_urlsafe(32)}")
    print(
        "\nStore these in your host's environment variables. Never commit them. If FIELD_ENCRYPTION_KEY is lost, "
        "encrypted banking details can't be read; if it leaks, rotate it."
    )


def create_admin(email: str) -> None:
    from .db import SessionLocal
    from .models import User
    from .security import MIN_PASSWORD_LENGTH, hash_password
    from .services import audit

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email.lower())):
            sys.exit("A user with that email already exists")
        user = User(email=email.lower(), password_hash=hash_password(password), role="admin")
        db.add(user)
        db.flush()
        audit(db, "cli", "user.create_admin", "user", user.id)
        db.commit()
    print(f"Admin {email} created. Sign in, then turn on two-factor authentication (POST /api/auth/2fa/setup).")


def daily_jobs() -> None:
    from .db import SessionLocal
    from .jobs import run_daily

    with SessionLocal() as db:
        print(run_daily(db))


def check_email(to: str | None) -> None:
    import smtplib
    import ssl

    from .config import get_settings
    from .emailer import OutgoingEmail, send_email

    s = get_settings()
    if s.resend_configured:
        if not s.email_configured:
            sys.exit("RESEND_API_KEY is set but SMTP_FROM (the sending address) is missing")
        recipient = to or s.admin_notify_email
        if not recipient:
            sys.exit("Give a recipient or set ADMIN_NOTIFY_EMAIL")
        test = OutgoingEmail(
            to=recipient, subject="Team Hub email test", text="If you can read this, Team Hub notifications will arrive."
        )
        sys.exit(0 if send_email(test) else "Resend refused the email; see the log line above")
    if not s.smtp_configured:
        sys.exit("Email is not configured (set RESEND_API_KEY and SMTP_FROM, or SMTP_HOST, SMTP_USER and SMTP_PASS)")
    try:
        ctx = ssl.create_default_context()
        if s.smtp_port == 465:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=20) as smtp:
                smtp.login(s.smtp_user, s.smtp_pass)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
                smtp.starttls(context=ctx)
                smtp.login(s.smtp_user, s.smtp_pass)
    except smtplib.SMTPAuthenticationError:
        sys.exit("Login refused. For Zoho use an application-specific password and the full mailbox address.")
    except (smtplib.SMTPException, OSError) as exc:
        sys.exit(
            f"Could not connect to {s.smtp_host}:{s.smtp_port}: {exc}. Try port 587, or check your host allows outgoing SMTP."
        )
    print(f"Logged in to {s.smtp_host} as {s.smtp_user}")
    recipient = to or s.admin_notify_email
    if recipient and send_email(
        OutgoingEmail(
            to=recipient, subject="Team Hub email test", text="If you can read this, Team Hub notifications will arrive."
        )
    ):
        print(f"Test email sent to {recipient}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-keys")
    p = sub.add_parser("create-admin")
    p.add_argument("email")
    sub.add_parser("daily-jobs")
    p = sub.add_parser("check-email")
    p.add_argument("to", nargs="?")
    args = parser.parse_args()
    if args.command == "generate-keys":
        generate_keys()
    elif args.command == "create-admin":
        create_admin(args.email)
    elif args.command == "daily-jobs":
        daily_jobs()
    elif args.command == "check-email":
        check_email(args.to)


if __name__ == "__main__":
    main()
