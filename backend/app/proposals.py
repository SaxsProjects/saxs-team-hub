"""Client proposals (SP-PRO): the Team Hub writes the first draft from a service preset, the founder adjusts it.

A proposal explains the client's need, the solution, scope, timeline and the investment. When the client
says yes, it becomes a draft quotation with the same price lines, so the normal quotation, invoice and
payout flow takes over. Prices are never invented: preset lines start at R0.00 until the founder prices them.
"""

from types import SimpleNamespace

from .config import Settings, get_settings
from .payouts import format_bp, format_zar
from .pdf import _d, _Doc, _queries, _short, _vat_totals

# The facts below are the company's own (registered, B-BBEE Level 1 EME, based in Limpopo); keep them true.
WHY_US = (
    "{legal} is a registered South African company (Registration No {reg}) based in Thohoyandou, Limpopo, with a "
    "B-BBEE Level 1 (EME) status. You deal directly with the founder from the first meeting to handover. Every "
    "project has a written scope, fixed prices per item, a documented handover, and the work becomes yours once "
    "it is paid in full."
)

PRESETS: dict[str, dict] = {
    "website": {
        "label": "Business website",
        "title": "Business website for {client}",
        "need": "{client} needs a professional website that explains its services, builds trust and makes it easy "
        "for customers to make contact, on phones as well as computers.",
        "solution": "We design and build a fast, mobile-friendly website with your branding, clear service pages, a "
        "contact form and WhatsApp/call buttons, set up for search engines and Google Maps.",
        "scope": "Design in your brand colours and logo\nUp to 5 pages (Home, About, Services, Gallery, Contact)\n"
        "Contact form and WhatsApp/call buttons\nBasic search-engine set-up and Google Business link\n"
        "Domain and hosting set-up (third-party costs billed at cost)\nHandover session and written guide",
        "timeline": "About 2 to 3 weeks from the deposit and the content (text, photos and logo).",
        "items": ["Website design and build", "Domain and hosting set-up", "Handover and training"],
    },
    "web_app": {
        "label": "Web system or portal",
        "title": "Web system for {client}",
        "need": "{client} needs to replace manual work (paper, spreadsheets or messages) with one secure system that "
        "the team can use from anywhere.",
        "solution": "We build a secure web application with user accounts and roles, the screens and reports your "
        "process needs, and a database that keeps your records safe and backed up.",
        "scope": "Requirements workshop and written specification\nUser accounts with roles and secure sign-in\n"
        "The agreed screens, forms and reports\nDatabase with daily backups\nTesting with your team\n"
        "Deployment, handover session and 30 days of fixes",
        "timeline": "About 4 to 8 weeks depending on the agreed specification; milestones are set in the specification.",
        "items": ["Requirements and specification", "Development of the agreed features", "Testing, deployment and handover"],
    },
    "mobile_app": {
        "label": "Mobile app (Android)",
        "title": "Android app for {client}",
        "need": "{client} wants customers or staff to use its service from their phones, including where data is "
        "expensive or the signal is weak.",
        "solution": "We build an Android app that is light on data, works offline where it can, and connects to a "
        "secure back end. It can be published on Google Play under your name.",
        "scope": "Screens and features as agreed in the specification\nSecure back end and database\n"
        "Offline support where practical\nTesting on real devices\nGoogle Play listing (in your developer account)\n"
        "Handover and 30 days of fixes",
        "timeline": "About 6 to 10 weeks depending on the agreed specification.",
        "items": ["App design and specification", "App and back-end development", "Testing, publishing and handover"],
    },
    "ecommerce": {
        "label": "Online shop",
        "title": "Online shop for {client}",
        "need": "{client} wants to sell online and accept payments safely, with stock and orders in one place.",
        "solution": "We set up an online shop with your products, secure South African payment options, order "
        "notifications and simple stock management.",
        "scope": "Shop design in your branding\nProduct catalogue set-up (first products loaded together)\n"
        "Payment gateway connection (gateway fees are charged by the provider)\nOrder emails and WhatsApp link\n"
        "Delivery and returns pages\nHandover and training",
        "timeline": "About 3 to 4 weeks from the deposit and product information.",
        "items": ["Shop design and build", "Payment and delivery set-up", "Product loading, handover and training"],
    },
    "automation": {
        "label": "Automation or AI assistant",
        "title": "Automation for {client}",
        "need": "{client} spends time on repetitive tasks (capturing, replying, reporting) that could run on their own.",
        "solution": "We automate the agreed tasks with reliable workflows and, where it helps, an AI assistant trained "
        "on your own information, with a person always able to step in.",
        "scope": "Process review and list of tasks to automate\nWorkflow set-up and testing\n"
        "Optional AI assistant on your own documents\nMonitoring and error alerts\nHandover and written guide",
        "timeline": "About 2 to 5 weeks depending on the number of workflows.",
        "items": ["Process review", "Automation build and testing", "Handover and monitoring set-up"],
    },
    "it_support": {
        "label": "Monthly support and maintenance",
        "title": "Monthly support for {client}",
        "need": "{client} needs its website or systems kept updated, secure and working, with someone to call.",
        "solution": "A monthly support agreement: updates, backups, security checks, small changes and help when "
        "something goes wrong.",
        "scope": "Software and security updates\nBackup checks\nUptime monitoring\nSmall content changes "
        "(agreed hours per month)\nSupport by email and WhatsApp on business days",
        "timeline": "Monthly, starting on the agreed date; either party may end it with one month's written notice.",
        "items": ["Monthly support and maintenance"],
    },
    "custom": {
        "label": "Custom proposal",
        "title": "Proposal for {client}",
        "need": "",
        "solution": "",
        "scope": "",
        "timeline": "",
        "items": [],
    },
}


def preset_list() -> list[dict]:
    return [{"key": key, "label": value["label"]} for key, value in PRESETS.items()]


def draft_from_preset(service: str, client_name: str, s: Settings | None = None) -> dict:
    """The first draft of a proposal for this client and service."""
    s = s or get_settings()
    p = PRESETS[service]
    fill = {"client": client_name}
    return {
        "service": service,
        "title": p["title"].format(**fill)[:200],
        "introduction": (
            f"Thank you for the opportunity to propose a solution to {client_name}. This proposal sets out what we "
            "understand you need, how we will deliver it, what it costs and how long it takes."
        ),
        "need": p["need"].format(**fill),
        "solution": p["solution"].format(**fill),
        "scope": p["scope"],
        "timeline": p["timeline"],
        "why_us": WHY_US.format(legal=s.company_legal_name, reg=s.company_registration_number or "on request"),
        "items": [{"description": d, "quantity": 1, "unit_price_cents": 0} for d in p["items"]],
    }


def proposal_lines(items: list[dict]) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            description=i["description"],
            quantity=i["quantity"],
            unit_price_cents=i["unit_price_cents"],
            line_total_cents=i["quantity"] * i["unit_price_cents"],
        )
        for i in items
    ]


def proposal_pdf(p, *, draft: bool, company: Settings | None = None) -> bytes:
    s = company or get_settings()
    doc = _Doc("PROPOSAL", watermark="DRAFT - NOT ISSUED" if draft else None, company=company, reference=p.number or "")
    doc.title_block(
        [
            ("Proposal No", p.number or "Draft (numbered when issued)"),
            ("Date", _d(p.issue_date)),
            ("Valid until", _d(p.valid_until)),
            ("For", _short(p.title)),
        ]
    )
    doc.parties("From", doc.from_lines(), "Prepared for", doc.client_lines(p.client))
    for heading, text in (
        ("Introduction", p.introduction),
        ("Your need", p.need),
        ("Our solution", p.solution),
    ):
        if text:
            doc.section_label(heading)
            doc.para(text)
    if p.scope:
        doc.box("Scope of work", [f"- {line.strip()}" for line in p.scope.splitlines() if line.strip()])
    if p.timeline:
        doc.section_label("Timeline")
        doc.para(p.timeline)
    if p.items:
        doc.section_label("Investment")
        doc.line_table(proposal_lines(p.items))
        vat_text = (
            f"Prices include VAT at {format_bp(p.vat_rate_bp)}."
            if p.vat_rate_bp
            else f"{s.company_legal_name} is not a registered VAT vendor, so no VAT is charged (VAT 0%)."
        )
        doc.bottom(
            [
                (
                    "Payment terms",
                    f"{s.deposit_percent}% deposit before work begins; balance on completion and handover. "
                    f"All prices are in South African Rand. {vat_text}",
                ),
                (
                    "Next step",
                    "Reply to accept this proposal. We then send a formal quotation and the service agreement to sign.",
                ),
            ],
            _vat_totals(p.subtotal_cents, p.vat_cents, p.vat_rate_bp),
            "TOTAL (ZAR)",
            format_zar(p.total_cents),
        )
    if p.why_us:
        doc.section_label(f"Why {s.company_name}")
        doc.para(p.why_us)
    if not draft:
        doc.signature_block("Issued by", p.issue_date)
    doc.closing("Thank you", _queries(s, "proposal"))
    return bytes(doc.output())
