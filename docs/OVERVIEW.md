# SaxsProjects Team Hub — the whole picture

*For the founder and for any AI agent working on this repository. Last updated 26 November 2026.*

## 1. What it is, in one paragraph

The Team Hub is SaxsProjects' private back office for its contractor team. It **recruits** people (formal offers they accept online with an e-signature), **onboards** them (a checklist, their banking details stored encrypted, signed documents), **tracks work** (projects shared by percentage, and fixed-fee Task Orders), **bills clients** (quotations, invoices, receipts, credit notes) and **works out what every contractor is owed and when** — then the founder pays by EFT from the Capitec Business account and records it. The system never moves money itself; that is a deliberate safety choice.

## 2. Where everything lives

| Thing | Where | Notes |
|---|---|---|
| Code | `github.com/SaxsProjects/saxs-team-hub` (private) | Branch `main` is what runs live |
| Server (API) | `https://saxs-team-hub-api.onrender.com` — Render, free plan, Frankfurt | Redeploys automatically when `main` changes. Sleeps when idle; first request can take ~1 minute |
| Database | Neon project `saxs-team-hub`, PostgreSQL 17, Frankfurt, database `teamhub` | Free plan |
| Secrets | `C:\Users\mamag\.saxs-team-hub\` on the founder's laptop (only that Windows account can open it), copied into Bitwarden and the Render dashboard | **Never** in the repository, chat, or logs |
| Backups | Weekly on GitHub (kept 90 days) and weekly on the laptop in `.saxs-team-hub\backups` (kept forever) | Encrypted |
| Screens | Not built yet | Everything works through the API today; the screens (frontend) come later |

## 3. Status (26 Nov 2026)

| Part | State |
|---|---|
| Offers, pipeline, onboarding, projects, payouts, Task Orders, rate history, finance documents | Built and tested (110 automated tests) |
| Dashboard and team overview data, payment list, Request payment | Built |
| Security hardening, encrypted backups, restore drill | Built; backups scheduled |
| Database live and locked down | Done |
| Server live | Live since 26 Nov 2026 (health, database guards and admin two-factor verified). Email moves to Resend over HTTPS because Render's free plan blocks SMTP |
| GitHub secrets for daily reminders and cloud backups | **Waiting** for the founder (values in `.saxs-team-hub\github-secrets.env`) |
| Screens (frontend) | Not started, on hold |

## 4. Who uses it

| Role | Who | What they can do |
|---|---|---|
| **Admin** | The founder | Everything. Two-factor login is required in production |
| **Team member** | A contractor who accepted an offer | See only their own: profile, onboarding checklist, projects and rate, Task Orders, payouts and statements, documents; request payment of a due payout |
| **Candidate** | Someone who received an offer | No account: opens a private link, reads the offer, accepts or declines |

## 5. How it works, start to finish

```
Recruit ─► Offer link ─► Accept (e-signature) ─► Account + onboarding ─► Work ─► Client pays ─► Payout due ─► Founder pays by EFT ─► Marked paid
                       └► Decline / expire ─► details deleted after a year (POPIA)
```

1. **Offer.** The founder adds a person, attaches the proposal PDF and sends the offer. The candidate gets a secret link (it expires at the deadline, works once, can be revoked).
2. **Accept or decline.** To accept, the candidate ticks a box and types their full name exactly. The system keeps proof: time, IP address, browser, and a fingerprint of the exact offer they accepted, and emails both sides an acceptance record (PDF). The founder is emailed when the offer is opened, accepted, declined or expires.
3. **Onboarding.** Accepting creates the team-member account (they set their own password through an emailed link) and a 7-item checklist: GitHub access, two-factor, channel joined, standards read, banking details, signed agreement, and so on. Banking/ID details are encrypted the moment they are saved.
4. **Work** comes in two kinds:
   - **Projects (revenue share).** Each project lists contributors and their share of the work. Shares lock once work starts or the first payment arrives, so nobody can change them afterwards.
   - **Task Orders (fixed fee).** The founder proposes a task (number `SP-TO-YYYY-NNN`, title, deliverable, fee, due date). The contractor confirms or declines, does the work and submits it; the founder accepts it within 5 days or asks for changes.
5. **Client money in.** The founder issues quotations and invoices (numbered `SP-Q-`, `SP-INV-`; once issued they can never be edited — mistakes are fixed with a credit note `SP-CN-`). Recording a payment issues a receipt (`SP-R-`) and, for a project, calculates every contributor's payout.
6. **Payouts.** Each payout has a statement PDF (`SP-PS-YYYY-NNN`) and a due date. Team members see theirs and, once it is due, can press **Request payment** — the founder gets an email.
7. **Paying.** The founder downloads the **payment list**, pays each person in the Capitec Business app, and marks each payout as paid with the EFT reference. The team member is notified and their statement updates.

## 6. The money rules (from the contractor agreements)

- Money is stored in whole cents, percentages in basis points (15% = 1500), and rounded once — so totals always reconcile.
- **Revenue share:** contributor earns `(money received − project costs) × their rate × their work share`. Rate is **15%**, or **20%** from the date of a written review. Each client instalment is shared at the rate in force on the day it was received. Nothing is ever clawed back: later costs reduce later payouts. Due 7 days after the client payment.
- **Task fees:** due 7 days after the task is accepted (`standard` terms). Contractors on **deferred** terms (agreements SP/ICA/2026/004 and 005 — Zwonaka and Thembi) wait for the company's First Client Payment: tasks accepted before it fall due 30 days after it; tasks accepted after it are due in 7 days.
- VAT is added only once the company has a VAT number. Payouts are based on money received excluding VAT.

## 7. How it is kept safe

| Risk | Protection |
|---|---|
| Stolen password | Strong hashing (argon2), 60-minute sessions, sign-out everywhere on password change, login rate limits, two-factor for the founder |
| A bug or attacker rewriting history | The audit log is append-only: the database itself refuses edits, deletes and wipes, for every login. Proven automatically on every code change and on the live database |
| A leaked app password | The app's database login can only read and write rows — it cannot change or drop tables, wipe them, or touch the audit history. Migrations use a separate login; backups use a read-only login |
| Personal data exposure (POPIA) | Banking and ID details encrypted; shown only when the founder deliberately reveals them (and that is logged). Declined candidates deleted after a year. Data stored in Frankfurt (EU), stated in the privacy notice (POPIA section 72) |
| Eavesdropping | Encrypted connections only (HTTPS; database refuses unencrypted connections) |
| Forged or altered documents | Issued documents are stored once with a fingerprint (SHA-256) and never regenerated; numbers never repeat or skip |
| Money sent wrongly | The system cannot send money. The founder approves every payment in the bank app |
| Losing everything | Encrypted, tamper-evident backups weekly in two places; restore tested automatically |
| Misconfiguration | In production the server refuses to start without strong secrets, encrypted database connections, email and the signature |

## 8. What runs on its own

| Job | When | What it does |
|---|---|---|
| Daily jobs (GitHub Actions → `POST /api/jobs/daily`) | Every morning | Expires overdue offers, emails due payouts and overdue Task Order reviews, expires old quotations, emails overdue invoices, applies POPIA deletion |
| Cloud backup (`.github/workflows/backup.yml`) | Sundays 02:30 | Encrypted backup kept 90 days as a private GitHub artifact |
| Laptop backup (Task Scheduler: "SaxsProjects Team Hub backup") | Sundays 10:00, or next time the laptop is on | Encrypted backup in `.saxs-team-hub\backups`, log in `backup.log` |
| Automated checks (CI) | Every code change | Lint, 110 tests, migrations on PostgreSQL, audit-log protection proof, backup/restore drill, dependency vulnerability scan |

## 9. Founder's everyday tasks (API today, screens later)

| Task | How |
|---|---|
| See the state of the business | `GET /api/dashboard` |
| Offer someone a role | `POST /api/people`, `POST /api/offers`, attach PDF, `POST /api/offers/{id}/send` |
| Give someone a task | `POST /api/task-orders`; accept with `POST /api/task-orders/{id}/accept` |
| Record client money | `POST /api/invoices/{id}/payments` or `POST /api/projects/{id}/payments` |
| Pay people | `GET /api/payment-list.csv` → pay in Capitec → `POST /api/payouts/{id}/paid` with the EFT reference |
| Record a rate review | `PATCH /api/people/{id}` with `rate_bp`, `rate_review_note`, `rate_effective_from` |

Interactive API documentation is at `/docs` on the server while `ENABLE_API_DOCS=true`.

---

## 10. For AI agents working on this repository

**Read first:** this file, then `docs/backend.md` (rules and endpoints), `docs/deploy.md` (production setup), `docs/backend-plan.md` (original plan and recorded deviations).

### Repository map
```
backend/
  app/
    main.py          app factory, security headers, /api/health, /api/jobs/daily
    config.py        settings from env; check_production_ready() refuses unsafe production config
    db.py            engine (pool tuned for Neon), UTCDateTime type
    models.py        all tables + status tuples; money = *_cents ints, rates = *_bp ints
    schemas.py       Pydantic request/response models
    security.py      argon2, JWT, TOTP, Fernet field encryption
    deps.py          auth dependencies (require_admin / require_member), rate limiters
    services.py      audit(), today_local() (Africa/Johannesburg), document storage
    payouts.py       payout maths (instalment-by-instalment, single rounding)
    terms.py         agreement date rules: rate_at, First Client Payment, task-fee due dates
    numbering.py     SP-* document numbers (row-locked counter per year)
    pdf.py           statements, invoices, acceptance records; signature loading
    emailer.py       Resend (HTTPS) or SMTP + notify_admin; in tests mails go to emailer.outbox
    jobs.py          daily jobs
    routers/         auth, people, offers, pages (public HTML), projects, task_orders, finance, me, overview
  alembic/versions/  migrations (batch mode; Postgres-only bits guarded by dialect)
  scripts/           neon_setup.py, check_db_guards.py, backup.py, local_backup.ps1
  tests/             pytest; conftest fixtures: client, admin, sent_offer, team
docs/                OVERVIEW.md (this), backend.md, deploy.md, backend-plan.md
.github/workflows/   ci.yml, daily-jobs.yml, backup.yml
render.yaml          Render blueprint
```

### Commands (run from `backend/`)
```
.venv/Scripts/python -m pytest -q          # all tests (SQLite); CI also runs PostgreSQL
.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .
DATABASE_URL=sqlite:///tmp.db alembic upgrade head && alembic check   # migrations match models
alembic revision --autogenerate -m "..."   # then NAME constraints by hand and add CHECKs autogenerate misses
```

### Invariants — never break these
1. **Money:** integer cents and basis points only; round once; never float.
2. **Issued documents are immutable.** Corrections are credit notes. Document numbers never repeat or skip.
3. **Audit log is append-only.** Never add code that updates or deletes `audit_log`. Audit entries hold ids, not names/emails/bank data.
4. **The system never moves money.** No payment-provider integrations that send funds without founder approval in the bank.
5. **Members see only their own data.** Every `/api/me/*` query filters by `user.person_id`; return 404 (not 403) for other people's records.
6. **Concurrent state changes lock the row** (`with_for_update()` + `populate_existing`).
7. **Every migration must pass `alembic check`** and be reversible; downgrades refuse rather than destroy data.
8. **Agreement rules live in `terms.py` / `payouts.py`** with tests citing the clause; change them only with the founder's confirmation.

### Secrets and safety rules
- Never print, log, commit or paste secrets (connection strings, keys, tokens). Scripts redact `postgres://…` in output.
- Secrets live only in `%USERPROFILE%\.saxs-team-hub\`, Bitwarden, Render and GitHub secrets.
- The founder personally enters: SMTP password, bank account number, passwords, OTPs; uploads the signature.
- Production database changes go through migrations and `scripts/neon_setup.py`, never ad-hoc SQL.

### Workflow
- Branch from `main` (`feature/…`, `fix/…`), open a PR, wait for CI to pass, then merge. Never force-push `main`.
- **No AI attribution anywhere:** no "Co-Authored-By", "Generated with" or similar in commits, PRs or docs. The work is published as the founder's.
- Keep `docs/backend.md` and this file up to date when behaviour changes.
