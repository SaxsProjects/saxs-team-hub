"""Company details printed on quotations, invoices, receipts and credit notes.

The server settings (COMPANY_*, SIGNATORY_*) are the starting values. Once the founder saves the details
in the app, the saved values win. They are stored encrypted in `company_profile` (one row).
The signature image stays a server secret file and is never editable from a browser.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import SessionLocal
from .models import CompanyProfile
from .security import decrypt_text, encrypt_text

# Settings fields the founder can change in the app.
EDITABLE = (
    "company_legal_name",
    "company_registration_number",
    "company_vat_number",
    "company_address",
    "company_email",
    "company_phone",
    "company_website",
    "company_whatsapp",
    "company_bank_name",
    "company_bank_account_name",
    "company_bank_account_number",
    "company_bank_branch_code",
    "company_bank_account_type",
    "signatory_name",
    "signatory_title",
)
BANK_FIELDS = tuple(f for f in EDITABLE if f.startswith("company_bank_"))


def saved_values(db: Session) -> dict[str, str]:
    row = db.scalar(select(CompanyProfile).order_by(CompanyProfile.id).limit(1))
    if not row:
        return {}
    data = json.loads(decrypt_text(row.data_enc) or "{}")
    return {k: v for k, v in data.items() if k in EDITABLE and isinstance(v, str)}


def company_settings(db: Session | None = None) -> Settings:
    """The server settings with the company details saved in the app applied on top."""
    base = get_settings()
    if db is None:
        with SessionLocal() as own:
            overrides = saved_values(own)
    else:
        overrides = saved_values(db)
    return base.model_copy(update=overrides) if overrides else base


def save_values(db: Session, values: dict[str, str], actor: str) -> None:
    row = db.scalar(select(CompanyProfile).order_by(CompanyProfile.id).limit(1))
    data_enc = encrypt_text(json.dumps({k: values[k] for k in EDITABLE}))
    if row:
        row.data_enc = data_enc
        row.updated_by = actor
    else:
        db.add(CompanyProfile(data_enc=data_enc, updated_by=actor))
