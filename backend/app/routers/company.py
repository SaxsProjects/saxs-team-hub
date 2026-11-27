"""The company details the founder edits in Settings. They print on quotations, invoices, receipts and statements.

Safeguards, because a changed bank account on an invoice is how invoice fraud works:
- founder only, with two-factor turned on;
- changing any banking detail needs the founder's current password;
- every change is audited (bank account numbers masked), and a bank change emails the founder at once.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..company import BANK_FIELDS, EDITABLE, company_settings, save_values
from ..db import get_db
from ..deps import require_admin
from ..emailer import notify_admin
from ..models import User
from ..security import verify_password
from ..services import audit

router = APIRouter(prefix="/api", tags=["company"])


class CompanyDetails(BaseModel):
    company_name: str = ""  # trading name: read-only here, set on the server
    company_legal_name: str = Field("", max_length=200)
    company_registration_number: str = Field("", max_length=40)
    company_vat_number: str = Field("", max_length=20)
    company_address: str = Field("", max_length=400)
    company_email: str = Field("", max_length=320)
    company_phone: str = Field("", max_length=40)
    company_website: str = Field("", max_length=200)
    company_bank_name: str = Field("", max_length=80)
    company_bank_account_name: str = Field("", max_length=120)
    company_bank_account_number: str = Field("", max_length=20)
    company_bank_branch_code: str = Field("", max_length=10)
    company_bank_account_type: str = Field("", max_length=40)
    signatory_name: str = Field("", max_length=120)
    signatory_title: str = Field("", max_length=80)


class CompanyIn(CompanyDetails):
    current_password: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("company_legal_name")
    @classmethod
    def _legal(cls, v: str) -> str:
        if len(v) < 2:
            raise ValueError("Enter the company's registered name")
        return v

    @field_validator("company_registration_number")
    @classmethod
    def _reg(cls, v: str) -> str:
        if v and not re.fullmatch(r"\d{4}/\d{6}/\d{2}", v):
            raise ValueError("Use the CIPC format, e.g. 2026/123456/07")
        return v

    @field_validator("company_vat_number")
    @classmethod
    def _vat(cls, v: str) -> str:
        if v and not re.fullmatch(r"4\d{9}", v):
            raise ValueError("A South African VAT number is 10 digits starting with 4")
        return v

    @field_validator("company_email")
    @classmethod
    def _email(cls, v: str) -> str:
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("company_bank_account_number")
    @classmethod
    def _account(cls, v: str) -> str:
        v = v.replace(" ", "")
        if v and not re.fullmatch(r"\d{6,16}", v):
            raise ValueError("The account number should be 6 to 16 digits")
        return v

    @field_validator("company_bank_branch_code")
    @classmethod
    def _branch(cls, v: str) -> str:
        if v and not re.fullmatch(r"\d{6}", v):
            raise ValueError("The branch code is 6 digits")
        return v


def _current(db: Session) -> CompanyDetails:
    s = company_settings(db)
    return CompanyDetails(company_name=s.company_name, **{k: getattr(s, k) for k in EDITABLE})


def _mask(field: str, value: str) -> str:
    if field == "company_bank_account_number" and value:
        return "•••• " + value[-4:]
    return value


def _require_2fa(user: User) -> None:
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Turn on two-factor authentication before changing company details")


@router.get("/company", response_model=CompanyDetails)
def get_company(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _current(db)


@router.put("/company", response_model=CompanyDetails)
def update_company(body: CompanyIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    _require_2fa(user)
    before = _current(db)
    new = {k: getattr(body, k) for k in EDITABLE}
    changed = [k for k in EDITABLE if new[k] != getattr(before, k)]
    if not changed:
        return before
    bank_changed = [k for k in changed if k in BANK_FIELDS]
    if bank_changed:
        if not body.current_password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter your current password to change banking details")
        if not verify_password(user.password_hash, body.current_password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That password is not right")
    save_values(db, new, user.email)
    audit(
        db,
        user.email,
        "company.update",
        "company",
        None,
        before={k: _mask(k, getattr(before, k)) for k in changed},
        after={k: _mask(k, new[k]) for k in changed},
    )
    db.commit()
    if bank_changed:
        account = _mask("company_bank_account_number", new["company_bank_account_number"])
        notify_admin(
            "Company banking details changed",
            "The banking details printed on your invoices were changed in the Team Hub by "
            f"{user.email}. New account: {new['company_bank_name']} {account}, "
            f"branch {new['company_bank_branch_code']}.\n\n"
            "If you did not make this change, sign in, change your password and set the banking details back at once.",
        )
    return _current(db)
