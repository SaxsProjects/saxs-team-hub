"""Company certificates (SP-CERT): one official design for every kind of certificate, not only shares.

The same drawing as the certificate template in the company template pack (navy frame, blue hairline, gold
inner line, logo and the gold company seal). Every issued certificate carries its number and a verification
link; anyone can check at /verify/<code> whether it is genuine and still valid.
"""

import io
import math
import secrets
from datetime import date
from pathlib import Path

from fpdf import FPDF

from .config import Settings, get_settings
from .pdf import _safe, load_signature

ASSETS = Path(__file__).parent / "assets"
LOGO_FULL = ASSETS / "logo-full.png"
LOGO_MARK = ASSETS / "logo-mark.png"

LINE = "______________________________"
# kind: (title, subtitle, lead, body template)
PRESETS: dict[str, tuple[str, str, str, str]] = {
    "completion": ("CERTIFICATE", "OF COMPLETION", "This is to certify that", f"has successfully completed {LINE}."),
    "achievement": (
        "CERTIFICATE",
        "OF ACHIEVEMENT",
        "This certificate is proudly presented to",
        f"in recognition of outstanding achievement in {LINE}.",
    ),
    "appreciation": ("CERTIFICATE", "OF APPRECIATION", "This certificate is presented to", f"in sincere appreciation of {LINE}."),
    "participation": ("CERTIFICATE", "OF PARTICIPATION", "This is to certify that", f"participated in {LINE}."),
    "recognition": ("CERTIFICATE", "OF RECOGNITION", "This certificate is awarded to", f"in recognition of {LINE}."),
    "training": (
        "CERTIFICATE",
        "OF TRAINING",
        "This is to certify that",
        f"has completed training in {LINE} presented by {{company}}.",
    ),
    "service": ("CERTIFICATE", "OF SERVICE", "This is to certify that", f"provided services to {{legal}} as {LINE}."),
    "project": (
        "PROJECT",
        "COMPLETION CERTIFICATE",
        "This certifies that {legal} has completed and handed over",
        f"{LINE} for {LINE}.",
    ),
    "partnership": ("CERTIFICATE", "OF PARTNERSHIP", "This certifies that", f"is a recognised partner of {{legal}} for {LINE}."),
    "custom": ("CERTIFICATE", "", "This is to certify that", ""),
}

NAVY, BLUE, GREY, INK = (21, 35, 63), (26, 95, 224), (90, 100, 117), (31, 41, 55)
GOLD, GOLD_DARK, GOLD_LIGHT = (176, 138, 52), (128, 96, 30), (222, 190, 110)
W, H = 297, 210
CX = W / 2


def preset(kind: str, s: Settings | None = None) -> dict:
    s = s or get_settings()
    title, subtitle, lead, body = PRESETS[kind]
    fill = {"company": s.company_name, "legal": s.company_legal_name}
    return {"kind": kind, "title": title, "subtitle": subtitle, "lead": lead.format(**fill), "body": body.format(**fill)}


def new_verify_code() -> str:
    return secrets.token_urlsafe(12)  # 16 characters, unguessable


def certificate_pdf(cert, *, verify_url: str | None, signed: bool, company: Settings | None = None) -> bytes:
    s = company or get_settings()
    legal = s.company_legal_name
    reg = s.company_registration_number
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_title(_safe(f"{cert.title.title()} {(cert.subtitle or '').title()} {cert.number}".strip()))
    pdf.set_author(_safe(legal))
    pdf.add_page()

    def centre(y, text, family="Helvetica", style="", size=10.0, color=INK, x=12.0, w=W - 24.0, spacing=0.0):
        pdf.set_font(family, style, size)
        pdf.set_char_spacing(spacing)
        pdf.set_text_color(*color)
        pdf.set_xy(x, y)
        pdf.cell(w, size * 0.42, _safe(text), align="C")
        pdf.set_char_spacing(0)

    # Frame
    pdf.set_fill_color(*NAVY)
    pdf.rect(8, 8, W - 16, H - 16, style="F")
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(11, 11, W - 22, H - 22, style="F")
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.35)
    pdf.rect(14, 14, W - 28, H - 28)
    pdf.set_line_width(0.9)
    for x, y, dx, dy in ((14, 14, 1, 1), (W - 14, 14, -1, 1), (14, H - 14, 1, -1), (W - 14, H - 14, -1, -1)):
        pdf.line(x, y, x + 14 * dx, y)
        pdf.line(x, y, x, y + 14 * dy)
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.25)
    pdf.rect(17, 17, W - 34, H - 34)
    if LOGO_MARK.exists():
        with pdf.local_context(fill_opacity=0.05):
            pdf.image(str(LOGO_MARK), x=CX - 45, y=74, w=90)

    # Logo and company line
    if LOGO_FULL.exists():
        pdf.image(str(LOGO_FULL), x=CX - 16, y=21, h=18.5)
    centre(42, legal.upper(), "Helvetica", "B", 10.5, NAVY, spacing=0.6)
    if reg:
        centre(46.5, f"Registration Number {reg}", "Helvetica", "", 8, GREY)

    # Title
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.3)
    pdf.line(CX - 70, 53, CX + 70, 53)
    centre(56.5, cert.title, "Times", "B", 30, NAVY, spacing=3)
    if cert.subtitle:
        centre(70, cert.subtitle, "Times", "", 15, BLUE, spacing=2)
    pdf.line(CX - 70, 78, CX + 70, 78)

    # Lead, name, body
    centre(85, cert.lead, "Times", "I", 13, GREY)
    size = 30.0
    pdf.set_font("Times", "BI", size)
    while pdf.get_string_width(_safe(cert.recipient_name)) > 200 and size > 18:
        size -= 1
        pdf.set_font("Times", "BI", size)
    centre(94, cert.recipient_name, "Times", "BI", size, NAVY)
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.4)
    pdf.line(CX - 85, 108, CX + 85, 108)
    if cert.body:
        pdf.set_font("Times", "", 12.5)
        pdf.set_text_color(*INK)
        pdf.set_xy(CX - 100, 113)
        pdf.multi_cell(200, 6.2, _safe(cert.body), align="C")

    _seal(pdf, CX, 162, 17, legal, reg)

    sy = 165
    image = load_signature() if signed else None
    if image:
        pdf.image(io.BytesIO(image), x=66, y=sy - 18, h=16)
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(0.3)
    pdf.line(42, sy, 118, sy)
    centre(sy + 2.5, s.signatory_name or "Authorised signatory", "Helvetica", "B", 9, NAVY, x=42, w=76)
    centre(sy + 7, s.signatory_title, "Helvetica", "", 8.5, GREY, x=42, w=76)

    centre(sy - 6, f"{cert.issue_date:%d %B %Y}", "Times", "", 12, INK, x=W - 118, w=76)
    pdf.line(W - 118, sy, W - 42, sy)
    centre(sy + 2.5, "Date", "Helvetica", "B", 9, NAVY, x=W - 118, w=76)
    centre(sy + 7, cert.place, "Helvetica", "", 8.5, GREY, x=W - 118, w=76)

    centre(H - 26, f"Certificate No. {cert.number}", "Helvetica", "B", 8, BLUE, spacing=0.4)
    check = f"Verify this certificate at {verify_url}" if verify_url else "To verify this certificate, quote its number"
    contact = s.company_email or ""
    centre(H - 22, "  |  ".join(v for v in (check, legal, contact) if v), "Helvetica", "", 6.8, GREY)
    return bytes(pdf.output())


def _seal(pdf: FPDF, cx: float, cy: float, r: float, legal: str, reg: str) -> None:
    teeth = 48
    pts = []
    for k in range(teeth * 2):
        a = math.pi * k / teeth
        rr = r if k % 2 == 0 else r * 0.94
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    pdf.set_fill_color(*GOLD)
    pdf.set_draw_color(*GOLD_DARK)
    pdf.set_line_width(0.15)
    pdf.polygon(pts, style="DF")
    pdf.set_fill_color(*GOLD_LIGHT)
    pdf.circle(cx, cy, r * 0.88, style="F")
    pdf.set_fill_color(*NAVY)
    pdf.circle(cx, cy, r * 0.84, style="F")
    pdf.set_draw_color(*GOLD_LIGHT)
    pdf.set_line_width(0.35)
    pdf.circle(cx, cy, r * 0.80, style="D")
    pdf.set_line_width(0.25)
    pdf.circle(cx, cy, r * 0.53, style="D")
    pdf.set_fill_color(255, 255, 255)
    pdf.circle(cx, cy, r * 0.50, style="F")
    if LOGO_MARK.exists():
        lw = r * 0.82
        pdf.image(str(LOGO_MARK), x=cx - lw / 2, y=cy - lw * 297 / 599 / 2, w=lw)

    def arc(text: str, mid_deg: float, radius: float, size: float, top: bool) -> None:
        pdf.set_font("Helvetica", "B", size)
        pdf.set_text_color(*GOLD_LIGHT)
        widths = [pdf.get_string_width(ch) + 0.25 for ch in text]
        span = sum(widths) / radius
        a = math.radians(mid_deg) + (span / 2 if top else -span / 2)
        for ch, w in zip(text, widths, strict=True):
            step = w / radius
            mid = a - step / 2 if top else a + step / 2
            x = cx + radius * math.cos(mid)
            y = cy - radius * math.sin(mid)
            rot = math.degrees(mid) - 90 if top else math.degrees(mid) + 90
            with pdf.rotation(rot, x, y):
                pdf.text(x - (w - 0.25) / 2, y + size * 0.35 / 2.83, ch)
            a = a - step if top else a + step

    arc(_safe(legal.upper())[:28], 90, r * 0.63, 5.6, top=True)
    if reg:
        arc(_safe(f"REG {reg}"), 270, r * 0.70, 5.2, top=False)


def is_valid(cert, today: date) -> bool:
    return cert.revoked_at is None and cert.issue_date <= today
