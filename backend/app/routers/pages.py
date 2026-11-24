"""Server-rendered pages for people who use links from emails.

Candidates open their offer link, team members set or reset their password.
These are plain HTML forms (no JavaScript), so they work in any browser and the
backend is usable on its own before the React frontend exists. They call the
same functions as the JSON API, so the rules (single-use links, typed-name
signature, expiry, rate limits, audit log) are identical.
"""

from html import escape

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import login_limiter, public_offer_limiter
from ..schemas import AcceptIn, DeclineIn, ForgotPasswordIn
from ..security import MIN_PASSWORD_LENGTH
from .auth import apply_password_token, forgot_password
from .offers import accept_offer, decline_offer, view_offer

router = APIRouter(include_in_schema=False)

PAGE_CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"

STYLE = """
body{margin:0;background:#f4f7fc;font-family:Arial,Helvetica,sans-serif;color:#15233F;line-height:1.55}
main{max-width:640px;margin:0 auto;padding:32px 16px}
.card{background:#fff;border:1px solid #dfe5ef;border-radius:12px;padding:24px;margin-bottom:16px}
h1{font-size:1.5rem;margin:0 0 8px;color:#1A5FE0}h2{font-size:1.1rem;margin:0 0 12px}
.brand{font-weight:700;color:#15233F;margin-bottom:16px}.brand span{color:#1A5FE0}
.muted{color:#5b6576;font-size:.9rem}dl{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:0}
dt{font-weight:700}dd{margin:0}label{display:block;font-weight:700;margin:12px 0 4px}
input[type=text],input[type=password],input[type=email],textarea{width:100%;box-sizing:border-box;padding:10px;
border:1px solid #b9c3d3;border-radius:8px;font:inherit}
.check{display:flex;gap:8px;align-items:flex-start;font-weight:400}
button{margin-top:16px;padding:12px 20px;border:0;border-radius:8px;background:#1A5FE0;color:#fff;font:inherit;
font-weight:700;cursor:pointer}button.secondary{background:#fff;color:#15233F;border:1px solid #b9c3d3}
.error{background:#fdecec;border:1px solid #f5c2c2;color:#8a1c1c;border-radius:8px;padding:12px;margin-bottom:16px}
.ok{background:#eaf7ee;border:1px solid #bfe5c9;border-radius:8px;padding:12px;margin-bottom:16px}
a{color:#1A5FE0}
"""


def page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    company = escape(get_settings().company_name)
    html = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex,nofollow"><title>{escape(title)} | {company}</title>'
        f"<style>{STYLE}</style></head><body><main>"
        f'<div class="brand"><span>{company[:4].lower()}</span>{company[4:].lower()} · Team Hub</div>'
        f"{body}</main></body></html>"
    )
    return HTMLResponse(html, status_code=status_code, headers={"Content-Security-Policy": PAGE_CSP})


def error_page(exc: HTTPException) -> HTMLResponse:
    return page(
        "Something went wrong", f'<div class="card"><h1>Sorry</h1><p>{escape(str(exc.detail))}</p></div>', exc.status_code
    )


# ---- Offers ---------------------------------------------------------------------------


def offer_body(token: str, offer, error: str | None = None, typed: str = "") -> str:
    t = escape(token)
    details = (
        f'<div class="card"><h1>{escape(offer.role)}</h1>'
        f'<p class="muted">Offer {escape(offer.reference)} from {escape(offer.company_name)}</p>'
        f"<dl><dt>For</dt><dd>{escape(offer.candidate_name)}</dd>"
        f"<dt>Respond by</dt><dd>{offer.deadline:%d %B %Y}</dd></dl>"
        + (f'<p style="white-space:pre-wrap">{escape(offer.message)}</p>' if offer.message else "")
        + (
            f'<p><a href="/api/public/offers/{t}/pdf" target="_blank" rel="noopener">Read the full offer (PDF)</a></p>'
            if offer.has_pdf
            else ""
        )
        + "</div>"
    )
    notice = f'<p class="muted">{escape(offer.privacy_notice)}</p>'
    if not offer.can_respond:
        status_text = {
            "accepted": "You accepted this offer. Thank you! Check your email for your acceptance record and next steps.",
            "declined": "You declined this offer. Thank you for letting us know.",
            "expired": "This offer has expired. Please contact us if you are still interested.",
        }.get(offer.status, f"This offer is {offer.status}.")
        return details + f'<div class="card"><p>{escape(status_text)}</p></div>' + notice
    err = f'<div class="error">{escape(error)}</div>' if error else ""
    forms = (
        f'<div class="card"><h2>Accept the offer</h2>{err}'
        f'<form method="post" action="/offer/{t}/accept">'
        f'<label for="sig">Type your full name exactly as shown above: {escape(offer.candidate_name)}</label>'
        f'<input id="sig" name="typed_signature" type="text" autocomplete="name" required value="{escape(typed)}">'
        f'<label class="check"><input type="checkbox" name="agree" value="yes" required> '
        f"I have read the offer and accept it. I agree that typing my name is my electronic signature.</label>"
        f'<button type="submit">Accept offer</button></form></div>'
        f'<div class="card"><h2>Decline the offer</h2>'
        f'<form method="post" action="/offer/{t}/decline">'
        f'<label for="reason">Reason <span class="muted">(optional)</span></label>'
        f'<textarea id="reason" name="reason" rows="3" maxlength="2000"></textarea>'
        f'<button type="submit" class="secondary">Decline offer</button></form></div>'
    )
    return details + forms + notice


@router.get("/offer/{token}", response_class=HTMLResponse, dependencies=[Depends(public_offer_limiter)])
def offer_page(token: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        offer = view_offer(token, background, db)
    except HTTPException as exc:
        return error_page(exc)
    return page(f"Offer {offer.reference}", offer_body(token, offer))


@router.post("/offer/{token}/accept", response_class=HTMLResponse, dependencies=[Depends(public_offer_limiter)])
def offer_accept_form(
    token: str,
    request: Request,
    background: BackgroundTasks,
    typed_signature: str = Form(""),
    agree: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        if len(typed_signature.strip()) < 2:
            raise HTTPException(400, "Please type your full name.")
        offer = accept_offer(
            token, AcceptIn(typed_signature=typed_signature[:200], agree=agree == "yes"), request, background, db
        )
    except HTTPException as exc:
        if exc.status_code == 400:
            try:
                current = view_offer(token, BackgroundTasks(), db)
            except HTTPException as inner:
                return error_page(inner)
            return page("Offer", offer_body(token, current, error=str(exc.detail), typed=typed_signature), 400)
        return error_page(exc)
    return page(
        "Offer accepted",
        '<div class="ok"><strong>Thank you, your acceptance has been recorded.</strong></div>' + offer_body(token, offer),
    )


@router.post("/offer/{token}/decline", response_class=HTMLResponse, dependencies=[Depends(public_offer_limiter)])
def offer_decline_form(
    token: str, request: Request, background: BackgroundTasks, reason: str = Form(""), db: Session = Depends(get_db)
):
    try:
        offer = decline_offer(token, DeclineIn(reason=reason[:2000] or None), request, background, db)
    except HTTPException as exc:
        return error_page(exc)
    return page("Offer declined", '<div class="ok">Your response has been recorded.</div>' + offer_body(token, offer))


# ---- Passwords --------------------------------------------------------------------------


def password_form(action: str, heading: str, token: str, error: str | None = None) -> str:
    err = f'<div class="error">{escape(error)}</div>' if error else ""
    return (
        f'<div class="card"><h1>{escape(heading)}</h1>{err}'
        f'<form method="post" action="{action}"><input type="hidden" name="token" value="{escape(token)}">'
        f'<label for="pw">New password <span class="muted">(at least {MIN_PASSWORD_LENGTH} characters)</span></label>'
        f'<input id="pw" name="password" type="password" autocomplete="new-password" minlength="{MIN_PASSWORD_LENGTH}" required>'
        f'<label for="pw2">Repeat the password</label>'
        f'<input id="pw2" name="confirm" type="password" autocomplete="new-password" required>'
        f'<button type="submit">Save password</button></form></div>'
    )


def handle_password(action: str, heading: str, token: str, password: str, confirm: str, db: Session) -> HTMLResponse:
    if len(password) < MIN_PASSWORD_LENGTH:
        return page(heading, password_form(action, heading, token, f"Use at least {MIN_PASSWORD_LENGTH} characters."), 400)
    if password != confirm:
        return page(heading, password_form(action, heading, token, "The two passwords don't match."), 400)
    try:
        apply_password_token(db, token, password[:200])
    except HTTPException as exc:
        return error_page(exc)
    return page(
        "Password saved",
        '<div class="card"><h1>Password saved</h1>'
        "<p>Your password has been set. You can now sign in to the Team Hub. "
        "For your security you have been signed out of any other devices.</p></div>",
    )


@router.get("/set-password", response_class=HTMLResponse)
def set_password_page(token: str = ""):
    return page("Set your password", password_form("/set-password", "Set your password", token))


@router.post("/set-password", response_class=HTMLResponse, dependencies=[Depends(login_limiter)])
def set_password_submit(token: str = Form(""), password: str = Form(""), confirm: str = Form(""), db: Session = Depends(get_db)):
    return handle_password("/set-password", "Set your password", token, password, confirm, db)


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(token: str = ""):
    return page("Reset your password", password_form("/reset-password", "Choose a new password", token))


@router.post("/reset-password", response_class=HTMLResponse, dependencies=[Depends(login_limiter)])
def reset_password_submit(
    token: str = Form(""), password: str = Form(""), confirm: str = Form(""), db: Session = Depends(get_db)
):
    return handle_password("/reset-password", "Choose a new password", token, password, confirm, db)


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page():
    return page(
        "Forgot password",
        '<div class="card"><h1>Forgot your password?</h1>'
        '<form method="post" action="/forgot-password"><label for="em">Your Team Hub email</label>'
        '<input id="em" name="email" type="email" autocomplete="email" required>'
        '<button type="submit">Email me a reset link</button></form></div>',
    )


@router.post("/forgot-password", response_class=HTMLResponse, dependencies=[Depends(login_limiter)])
def forgot_password_submit(background: BackgroundTasks, email: str = Form(""), db: Session = Depends(get_db)):
    try:
        forgot_password(ForgotPasswordIn(email=email.strip()), background, db)
    except ValueError:
        pass  # invalid email: same response, so the page reveals nothing
    return page(
        "Check your email",
        '<div class="card"><h1>Check your email</h1>'
        "<p>If that address has a Team Hub account, we've sent a link to reset the password. "
        "It is valid for 1 hour.</p></div>",
    )
