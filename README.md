# SaxsProjects Team Hub

Internal platform for **recruiting, onboarding and paying** the SaxsProjects team.

It replaces sending PDFs on WhatsApp and tracking replies by hand. With it, SaxsProjects can send a formal offer, record an accept or decline with proof, onboard new team members securely, and calculate project-based payouts accurately.

> **Status:** backend built (phases 0–4: offers, pipeline, notifications, onboarding, payouts) with tests and CI. The frontend is still to be built. See [docs/backend.md](docs/backend.md).

---

## 1. Problem

SaxsProjects is a start-up that engages developers as **independent contractors**, paid a percentage of the net income of each project they work on. Today:

- offers are sent as PDFs over WhatsApp and email, with no record of when they were opened or answered;
- accepts and declines arrive informally, so there is no reliable proof of what was agreed;
- onboarding steps (GitHub access, two-factor login, NDA) live in the founder's head;
- payout shares are worked out by hand, which is slow and easy to dispute.

## 2. Goals

1. Send each candidate a **personal, secure offer link**.
2. Let candidates **accept** (with a typed-name e-signature) or **decline** (with an optional reason), recorded with a timestamp.
3. Notify the founder **immediately** when an offer is viewed, accepted or declined.
4. Track every person through a clear **pipeline**.
5. Run a repeatable **onboarding checklist** for each new team member.
6. Record client payments and project costs, and **calculate contractor payouts automatically** under the contractor agreement (15% initial rate, 20% after written review).
7. Handle personal information in line with **POPIA**.

### Non-goals (v1)

- Payroll for employees (PAYE/UIF). Team members are contractors.
- Moving money. The Hub calculates and records payouts; payment is made by bank EFT outside the system.
- A public job board or applicant marketplace.

---

## 3. Users

| Role | Who | Can do |
|---|---|---|
| **Admin** | Founder | Everything: create offers, view the pipeline, manage onboarding, record income, approve payouts |
| **Candidate** | Person receiving an offer | Open their offer link, download the PDF, accept or decline |
| **Team member** | Accepted contractor | Sign in, see their onboarding checklist, projects, work shares and payout statements |

---

## 4. Modules

### 4.1 Offers

- Create an offer from a template: name, role, reference number, response deadline and attached proposal PDF.
- Generate a **single-use, unguessable link** (random token, stored as a hash, with an expiry date).
- The candidate opens the link without needing an account and reads the offer online or downloads the PDF.
- **Accept:** the candidate types their full name as an e-signature and confirms. The system records the timestamp, IP address and user agent, and stores a hash of the exact offer version they accepted.
- **Decline:** an optional reason box, followed by a gracious confirmation message.
- Electronic signatures are recognised under the Electronic Communications and Transactions Act 25 of 2002 (ECTA).

### 4.2 Pipeline

`Draft → Sent → Viewed → Accepted / Declined / Expired → Agreement signed → Onboarded`

- A board view and a list view, with overdue offers highlighted.
- Automatic reminder to the founder the day after a deadline passes.
- A full **audit log** of every status change.

### 4.3 Notifications

- Email to the founder on *viewed*, *accepted*, *declined* and *expired*.
- A confirmation email to the candidate after they respond.
- Optional later: WhatsApp notifications through the WhatsApp Business API.

### 4.4 Onboarding

A checklist created automatically when someone accepts:

- [ ] Contractor agreement signed (after company registration is finalised)
- [ ] GitHub account invited to the SaxsProjects organisation, with least-privilege access
- [ ] Two-factor authentication confirmed
- [ ] Team communication channel joined
- [ ] Banking details captured (stored encrypted)
- [ ] Coding standards and security rules read
- [ ] First task assigned

### 4.5 Projects and payouts

- Record a **project**, its client, its contributors and each contributor's **agreed work share**. The share is locked once work begins, in line with the contractor agreement.
- Record **client payments**, including instalments, and **direct project costs** (hosting, domains, tools, fees).
- Payout calculation:

  ```text
  net_project_income   = client_amount_received - direct_project_costs
  contributor_payout   = net_project_income x contributor_rate x contributor_work_share
  contributor_rate     = 0.15 (initial) | 0.20 (after written review)
  ```

- Payouts become **due 7 days after** a client payment is received. No client payment means no payout.
- A **statement** for each contributor (PDF) showing the amount received, the costs and the calculation, as promised in the contractor agreement.
- The founder marks a payout as *paid*, with the EFT reference.

### 4.6 Documents

- Store proposal PDFs, signed acceptance pages and contractor agreements for each person.
- Each document is versioned and hashed, so what was signed can always be proven.

---

## 5. Architecture

```text
React + Vite + TypeScript (Vercel)
        |  HTTPS / JSON
FastAPI (Python) API (Render)
        |
PostgreSQL (Neon)        Object storage for PDFs
        |
Email (SMTP / transactional email provider)
```

| Layer | Choice | Why |
|---|---|---|
| Frontend | React, Vite, TypeScript, Tailwind CSS | Already used across SaxsProjects; good for junior developers to learn |
| Backend | FastAPI (Python), SQLAlchemy, Alembic | Fast to build and readable; typed request validation with Pydantic |
| Database | PostgreSQL on Neon | Relational data with strict money rules; free tier to start |
| Hosting | Vercel (frontend), Render (API) | Existing SaxsProjects accounts; free tiers to start |
| Auth | Email and password with argon2 hashing, short-lived JWT sessions; admin two-factor authentication | Admin access protects personal and financial data |
| PDFs | Server-side generation for statements | Consistent, branded documents |
| Email | SMTP to start, transactional provider later | Free to begin with |

### Core data model

| Table | Key fields |
|---|---|
| `people` | id, full_name, email, phone, status, created_at |
| `offers` | id, person_id, role, reference, deadline, pdf_document_id, token_hash, token_expires_at, status |
| `offer_responses` | id, offer_id, decision, typed_signature, reason, ip, user_agent, offer_hash, responded_at |
| `onboarding_items` | id, person_id, item, done, done_at |
| `projects` | id, client_name, description, status |
| `project_contributors` | project_id, person_id, work_share, rate, locked_at |
| `client_payments` | id, project_id, amount_cents, received_at, reference |
| `project_costs` | id, project_id, description, amount_cents, incurred_at |
| `payouts` | id, project_id, person_id, client_payment_id, amount_cents, due_at, paid_at, eft_reference |
| `documents` | id, person_id, kind, storage_key, sha256, version, created_at |
| `audit_log` | id, actor, action, entity, entity_id, before, after, at |

Money is stored as **integer cents (ZAR)**, never as floating point.

---

## 6. Security and POPIA

- **Least data:** collect only what is needed. ID numbers and banking details are optional until they are actually required, and are **encrypted at rest**.
- **Offer links:** high-entropy random tokens, stored only as hashes, single-use for responses and expiring after the deadline.
- **Access control:** a candidate sees only their own offer, and a team member only their own data and statements. Admin-only routes are enforced on the server.
- **Secrets:** never committed. Use `.env` files (git-ignored) with a committed `.env.example` holding placeholders only.
- **Audit trail:** every offer response, status change and payout is logged and never edited.
- **Security headers and HTTPS only** (CSP, HSTS, X-Frame-Options), with rate limiting on public offer endpoints.
- **Retention:** declined-candidate data is deleted after a defined period (for example 12 months), with a POPIA notice shown on every offer page.
- **Dependencies:** versions pinned, with `npm audit` and `pip-audit` run in CI.

---

## 7. Delivery Plan

| Phase | Scope | Outcome |
|---|---|---|
| **0. Foundation** | Repository structure, CI (lint, type-check, tests), environments, `.env.example` | Empty but deployable app |
| **1. Offers MVP** | Admin login, create offer, upload PDF, personal link, accept/decline, email alerts, audit log | Offers sent and answered through the Hub |
| **2. Pipeline** | Board and list views, deadlines, reminders, document storage | One view of every candidate |
| **3. Onboarding** | Checklists, team member login, banking details (encrypted) | Repeatable, secure onboarding |
| **4. Payouts** | Projects, work shares, client payments, costs, payout calculation, PDF statements | Accurate, transparent contractor payouts |
| **5. Hardening** | Security review, POPIA notice and retention jobs, backups, monitoring | Ready for regular use |

Each phase ends with a working, tested release.

## 8. Definition of Done

- Feature works end to end in the deployed environment.
- Tests cover the business rules, especially offer-token handling and payout calculations.
- Lint and type checks pass in CI.
- No secrets in the repository.
- Docs updated.

## 9. Planned Repository Structure

```text
saxs-team-hub/
├─ frontend/          React + Vite + TypeScript app
├─ backend/           FastAPI app, SQLAlchemy models, Alembic migrations
│  ├─ app/
│  └─ tests/
├─ docs/              Decisions, data model, POPIA notice
├─ .github/workflows/ CI pipelines
└─ README.md
```

## 10. Getting Started

### Run the backend locally

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # then fill in SECRET_KEY etc.
python -m app.cli generate-keys      # paste the output into .env
alembic upgrade head                 # create the database tables
python -m app.cli create-admin you@saxsprojects.co.za
uvicorn app.main:app --reload        # API on http://localhost:8000, docs at /docs
```

Run the checks: `pytest`, `ruff check .`, `ruff format --check .`.

### Deploy (Render + Neon)

1. Create a free PostgreSQL database on [Neon](https://neon.tech) and copy its connection string.
2. In Render choose **New → Blueprint** and pick this repository; [`render.yaml`](render.yaml) sets up the API. Fill in the secret values it asks for, using `python -m app.cli generate-keys` for `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` and `JOBS_TOKEN`.
3. Email goes through **Zoho Mail**: `SMTP_HOST=smtppro.zoho.com` (or `smtp.zoho.com` for a free @zoho.com address), port 465, your full Zoho address, and an app-specific password from Zoho Accounts → Security → App Passwords. Check it from the Render shell with `python -m app.cli check-email`.
4. From the Render shell, run `python -m app.cli create-admin you@saxsprojects.co.za`, sign in, and turn on two-factor authentication (`/api/auth/2fa/setup` then `/api/auth/2fa/enable`). Admin routes stay locked until it is on.
5. Add the repository secrets `TEAM_HUB_API_URL` and `TEAM_HUB_JOBS_TOKEN` so the daily jobs run.

Keep `FIELD_ENCRYPTION_KEY` safe and backed up: without it, stored banking details can't be read.

---

**SaxsProjects** · We build digital solutions · saxsprojects.dev@gmail.com
