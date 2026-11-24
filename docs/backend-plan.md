# SaxsProjects Operations Backend: Build Plan (Tasks 14–21)

**Version:** 1.0 · **Date:** 24 November 2026 · **Owner:** Phathutshedzo Mamagau, Founder & Lead Developer

This plan covers the backend for two internal tools:

| Founder-plan task | Tool | What it does |
|---|---|---|
| 14 | Admin | Data model |
| 15 | Admin | Quote, invoice and receipt PDFs with automatic numbering |
| 16 | Admin | Payout calculations at 15% and 20% |
| 17 | Admin | Deployment on free tiers, banking details kept out of code |
| 18 | Team Hub | Offers |
| 19 | Team Hub | Onboarding |
| 20 | Team Hub | Contractor payouts |
| 21 | Team Hub | Protected personnel records (POPIA) |

The aims are a backend that is **stable**, **secure**, and produces records and documents that show SaxsProjects is a **real, organised company that is ready to trade**.

---

## 1. Key Decisions

### 1.1 One backend, one database, two modules

Build **one API service** with two modules, not two separate apps.

- Payouts appear in both tools (task 16 and task 20). One database means one source of truth for clients, projects, money received, costs and payouts. There is no copying of data and no figures that disagree.
- One deployment, one set of secrets, one security review.

```text
                 ┌─────────────────────────────┐
  Admin web app ─┤                             │
  Team Hub app  ─┤   SaxsProjects Ops API      ├── PostgreSQL (Neon)
  Offer links   ─┤   FastAPI · Python 3.12     │
                 │   modules: finance, team    ├── Email (Zoho SMTP or HTTPS email API)
                 └─────────────────────────────┘
```

- **Code location:** `saxs-team-hub/backend/`. The `saxs-admin-kit` repository stays as the home of checklists, templates and policies.
- **Public addresses:** `api.saxsprojects.co.za` (API) and `hub.saxsprojects.co.za` (web app). The website's CSP already allows `api.saxsprojects.co.za`.

### 1.2 Technology

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Stable, readable, good libraries for money and PDFs |
| Framework | FastAPI + Pydantic v2 | Typed request validation; automatic OpenAPI docs |
| Database | PostgreSQL 16 on Neon (free tier) | Transactions and row locks for money and numbering |
| ORM and migrations | SQLAlchemy 2.0 + Alembic | Every schema change is versioned and reversible |
| PDFs | ReportLab | Pure Python with no system libraries, so builds are reliable on Render |
| Passwords | argon2id (`argon2-cffi`) | Current best practice |
| Two-factor login | TOTP (`pyotp`) | Works with the authenticator app you already use |
| Field encryption | AES-256-GCM (`cryptography`) | For ID numbers and banking details |
| Hosting | Render (API), Vercel (frontend), Neon (database) | Accounts already exist; free tiers to start |
| CI | GitHub Actions | ruff, mypy, pytest, pip-audit, gitleaks |

Pin every dependency to an exact version in `requirements.txt` (generate it with `pip-compile` so hashes are included).

### 1.3 Ground rules

1. **Money is stored as integer cents (ZAR).** Never use floats. Use `Decimal` for rates and shares, and round half-up to the cent once, at the end.
2. **Issued documents are never edited or deleted.** A mistake on an invoice is corrected with a credit note, not by changing the invoice.
3. **Every change to money, documents or personal data is written to an append-only audit log.**
4. **No secrets, banking details or personal data in the repository.** They live in environment variables or in encrypted database fields.
5. **Every endpoint enforces access on the server.** The frontend never decides what someone may see.

---

## 2. Data Model (Task 14)

### 2.1 Shared tables

| Table | Key fields | Notes |
|---|---|---|
| `users` | id, email (unique, lower-case), password_hash, role (`admin` / `team_member`), totp_secret_enc, is_active, last_login_at | Admins must have TOTP switched on |
| `sessions` | id, user_id, refresh_token_hash, user_agent, ip, created_at, expires_at, revoked_at | Allows sign-out everywhere |
| `audit_log` | id, actor_user_id, action, entity, entity_id, before_json, after_json, ip, at | Insert only: the database user cannot UPDATE or DELETE rows |
| `company_settings` | key, value | Trading name, registration number, address, VAT status. **Banking details are not stored here** (see 5.3) |

### 2.2 Finance module

| Table | Key fields | Notes |
|---|---|---|
| `clients` | id, name, registration_or_id_no, contact_name, email, phone, address, created_at | |
| `projects` | id, client_id, code, name, status (`quoted` / `active` / `completed` / `cancelled`), started_at, completed_at | |
| `quotations` | id, number, client_id, project_id, issue_date, valid_until, status (`draft` / `issued` / `accepted` / `declined` / `expired`), subtotal_cents, total_cents, terms_version, pdf_sha256 | Number assigned only when issued |
| `invoices` | id, number, client_id, project_id, quotation_id, issue_date, due_date, status (`draft` / `issued` / `part_paid` / `paid` / `void`), total_cents, pdf_sha256 | |
| `line_items` | id, document_type, document_id, description, quantity, unit_price_cents, line_total_cents, sort_order | Shared by quotations and invoices |
| `payments_received` | id, invoice_id, project_id, amount_cents, received_on, method, bank_reference, proof_document_id | One row per client payment, including instalments |
| `receipts` | id, number, payment_id, issue_date, pdf_sha256 | One receipt per payment |
| `credit_notes` | id, number, invoice_id, reason, amount_cents, issue_date, pdf_sha256 | Corrects an issued invoice |
| `project_costs` | id, project_id, description, category, amount_cents, incurred_on, proof_document_id | Direct Project Costs, as defined in the contractor agreement |
| `document_sequences` | doc_type, year, last_number | Source of gapless numbering (section 3.2) |

### 2.3 Team module

| Table | Key fields | Notes |
|---|---|---|
| `people` | id, full_name, email, phone, status (`candidate` / `active` / `former`), created_at | |
| `personnel_records` | person_id, id_number_enc, bank_name_enc, bank_account_enc, branch_code_enc, key_id, updated_at | Encrypted fields only (section 6) |
| `offers` | id, person_id, reference, engagement_type (`revenue_share` / `task_fee`), response_deadline, proposal_document_id, token_hash, token_expires_at, status, offer_sha256 | |
| `offer_events` | id, offer_id, event (`sent` / `viewed` / `accepted` / `declined` / `expired`), typed_signature, reason, ip, user_agent, at | Insert only |
| `agreements` | id, person_id, reference (for example `SP/ICA/2026/003`), version, signed_on, document_id, ends_on | Records the 12-month fixed term |
| `onboarding_items` | id, person_id, item_key, done, done_at, done_by | Created from a template on acceptance |
| `project_contributors` | project_id, person_id, work_share (Decimal), locked_at | Shares on a project must total ≤ 100%. Locked when work starts |
| `rate_periods` | id, person_id, rate (0.15 or 0.20), effective_from, review_document_id | 20% requires a written review document |
| `task_orders` | id, person_id, reference, description, deliverable, fee_cents, due_on, status (`proposed` / `confirmed` / `submitted` / `accepted` / `rejected`), accepted_on | Task-fee contractors |
| `payouts` | id, person_id, kind (`revenue_share` / `task_fee`), project_id, payment_id, task_order_id, amount_cents, calculation_json, due_on, status (`due` / `paid` / `cancelled`), paid_on, eft_reference, statement_number | `calculation_json` keeps every input, so any payout can be explained |
| `documents` | id, owner_type, owner_id, kind, filename, content_type, size_bytes, sha256, storage, created_at | Uploaded and generated files |
| `retention_schedule` | entity, entity_id, delete_after, reason | Drives the POPIA clean-up job |

Every table has `created_at`, `updated_at` and `created_by`. Use UUID primary keys, so record IDs cannot be guessed from URLs.

**Done when:** Alembic migration `0001` creates every table with foreign keys, `CHECK` constraints (amounts ≥ 0, shares between 0 and 1, rates only 0.15 or 0.20) and indexes. `alembic upgrade head` followed by `alembic downgrade base` runs cleanly in CI.

---

## 3. Quotes, Invoices and Receipts (Task 15)

### 3.1 Document numbers

| Document | Format | Example |
|---|---|---|
| Quotation | `SP-Q-YYYY-NNN` | SP-Q-2026-001 |
| Invoice | `SP-INV-YYYY-NNN` | SP-INV-2026-001 |
| Receipt | `SP-R-YYYY-NNN` | SP-R-2026-001 |
| Credit note | `SP-CN-YYYY-NNN` | SP-CN-2026-001 |
| Payout statement | `SP-PS-YYYY-NNN` | SP-PS-2026-001 |

The counter restarts at 001 each calendar year. These formats match the price list (SP/PRC/2026/001) and the Canva templates.

### 3.2 Gapless numbering

Numbers are assigned **only at the moment a document is issued**, inside the same database transaction:

```sql
SELECT last_number FROM document_sequences
 WHERE doc_type = :type AND year = :year
 FOR UPDATE;                       -- locks the row; two issues can never get the same number
UPDATE document_sequences SET last_number = last_number + 1 ...;
-- then set the number on the document, render the PDF, store its SHA-256, COMMIT
```

If anything fails before the commit, the whole transaction rolls back and no number is used up. Drafts have no number. A `UNIQUE (number)` constraint on each table is the final safety net.

### 3.3 PDF content

Use the same look as the Canva templates: logo, blue `#1A5FE0`, navy `#15233F`, Arial (Helvetica in ReportLab).

| Every document | Quotation adds | Invoice adds | Receipt adds |
|---|---|---|---|
| Logo, company name, registration number, address, email, phone, website, document number, date, client details | Scope, line items, total, "valid for 30 days", payment terms (50% deposit), warranty summary | Due date (+7 days), quotation reference, banking details, "use the invoice number as your payment reference" | Amount received, payment date, method, invoice paid, balance outstanding |

- The words "Tax Invoice" and VAT appear **only** when `company_settings.vat_registered = true`.
- Until the registration number is set, every PDF prints a red **DRAFT – NOT VALID FOR PAYMENT** watermark, and the API refuses to issue invoices. This stops an incomplete invoice from ever reaching a client.
- PDFs are generated the same way every time from the stored data. The SHA-256 saved at issue time proves later that a copy is unchanged.

### 3.4 Endpoints

```text
POST /api/quotations                  create draft
POST /api/quotations/{id}/issue       assign number, render PDF, lock
POST /api/quotations/{id}/accept      record acceptance; creates the project
POST /api/invoices                    create draft (optionally from a quotation)
POST /api/invoices/{id}/issue
POST /api/invoices/{id}/payments      record a payment; issues a receipt automatically
POST /api/invoices/{id}/credit-notes
GET  /api/documents/{id}/pdf          admin, or the owning team member only
```

**Done when:** tests prove that 50 parallel issue requests produce 50 unique numbers in sequence with no gaps, that an issued document cannot be changed (HTTP 409), and that the PDF hash matches on re-download.

---

## 4. Payout Calculations (Tasks 16 and 20)

### 4.1 Revenue-share contractors (developers)

These rules come from the contractor agreements SP/ICA/2026/001 and 002:

```text
Net Project Income  = money actually received from the client (excl. VAT) − Direct Project Costs
Contractor share    = Net Project Income × rate × agreed work share
rate                = 15% for the first 6 months; 20% from the date a written review confirms it
due date            = 7 days after the client payment is received
```

Clients often pay in instalments, so use the **cumulative method**. Each time a payment arrives:

```text
cumulative_net      = total received on project to date − total direct costs to date
entitlement_to_date = cumulative_net × rate_at_payment_date × work_share
payout_now          = entitlement_to_date − payouts already made on this project (never below 0)
```

- A cost recorded after an earlier payout lowers the next payout. It never creates a negative payout or a debt.
- The rate is taken from `rate_periods` at the date of the client payment.
- Rounding happens once, half-up to the cent. The full working is saved in `calculation_json`.
- **No client payment means no payout.** The code has no path to create a payout without a `payment_received` row.

**Worked check.** This example matches the illustration in the contractor agreement and becomes a unit test:

| Item | Amount |
|---|---|
| Received from client | R20,000.00 |
| Direct Project Costs | R2,000.00 |
| Net Project Income | R18,000.00 |
| Share at 15% (100% work share) | **R2,700.00** |
| Share at 20% | **R3,600.00** |

### 4.2 Task-fee contractors (operations and HR)

Under SP/ICA/2026/003:

- A Task Order holds the fee (R200–R500), the deliverable and the due date. It is binding once both sides confirm it.
- When the founder marks a task as **accepted**, a payout is created, due **7 days later**.
- The founder must accept or reject a submitted task within 5 days. Overdue reviews show on the dashboard.

### 4.3 Payout statements

Each payout produces an **SP-PS** statement PDF showing: client amount received, Direct Project Costs, Net Project Income, rate, work share, amount and due date (or task, fee and acceptance date). The contractor agreements promise this statement.

The founder marks a payout as paid with the EFT reference. The system never moves money.

**Done when:** property-based tests (`hypothesis`) show that, across thousands of random payment and cost sequences, total payouts never exceed the entitlement, are never negative, and always reconcile to the cent.

---

## 5. Deployment on Free Tiers (Task 17)

### 5.1 Environments

| Environment | API | Database | Purpose |
|---|---|---|---|
| Local | `uvicorn` | Docker Postgres 16 | Development |
| Staging | Render free web service | Neon branch `staging` | Testing with fake data only |
| Production | Render free web service | Neon branch `main` | Real records |

The Render free plan sleeps after inactivity, so the first request can take up to about a minute. That is acceptable for internal tools. Moving to a paid instance later needs no code changes.

### 5.2 Configuration

All configuration comes from environment variables. Commit a `.env.example` containing **placeholders only**.

```text
DATABASE_URL=postgresql+psycopg://user:password@host/db?sslmode=require
JWT_SIGNING_KEY=change-me
FIELD_ENCRYPTION_KEYS=k1:base64-32-byte-key        # comma-separated for key rotation
ACTIVE_ENCRYPTION_KEY_ID=k1
COMPANY_BANK_NAME=
COMPANY_BANK_ACCOUNT=
COMPANY_BANK_BRANCH=
SMTP_HOST=smtppro.zoho.com
SMTP_USER=
SMTP_PASS=
FRONTEND_ORIGINS=https://hub.saxsprojects.co.za
```

### 5.3 Banking details kept out of the code

- **Company banking details** are set only in Render's environment variables and read at runtime to print on invoices. They are never stored in the repository and never stored in plain text in the database.
- **Contractor banking details and ID numbers** are encrypted per field (section 6).
- `gitleaks` runs in CI and as a pre-commit hook, and the build fails on any leaked secret.

### 5.4 Email

Use Zoho SMTP from `noreply@` or `info@saxsprojects.co.za`. Some free hosting plans block outgoing SMTP ports, so test it on Render first with a startup check. If it is blocked, switch to an HTTPS email API with a free tier (for example Zoho ZeptoMail or Brevo). Write the email code behind a small `EmailSender` interface so the switch is a one-file change.

### 5.5 Backups and recovery

- Neon's free tier keeps only a short restore window, so add a **nightly GitHub Actions job**: `pg_dump` → encrypt with `age` → store as a private workflow artifact kept for 14 days.
- Test a full restore into the staging branch once a month, and record the date in the compliance calendar.

### 5.6 Release process

- Every pull request runs ruff, mypy (strict), pytest (≥ 85% coverage on the `finance` and `payouts` packages), pip-audit and gitleaks.
- Merging to `main` deploys to staging. Production deploys only when a release is tagged.
- Migrations run automatically before the new version starts (`alembic upgrade head` in Render's pre-deploy command).
- Health check endpoint `GET /api/health` checks the database connection and the migration version.

**Done when:** both environments run, a fresh clone deploys using only the documented steps, and `gitleaks` reports nothing across the full git history.

---

## 6. Security and POPIA (Tasks 18, 19, 21 and throughout)

### 6.1 Authentication

- argon2id password hashing. Minimum 12 characters, checked against a breached-password list.
- **TOTP two-factor is mandatory for admin accounts.** Backup codes are shown once and stored as hashes.
- Short-lived access tokens (15 minutes) plus a rotating refresh token in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie. A reused refresh token revokes the whole session.
- Lock out after 5 failed logins (15 minutes). Every login, failure and lockout goes to the audit log.

### 6.2 Authorisation

| Role | Can see and do |
|---|---|
| Admin (founder) | Everything. Every action is logged |
| Team member | Only their own profile, onboarding checklist, task orders, payouts and statements |
| Candidate (offer link) | Only the one offer behind their link. No account needed |

These rules are enforced in one dependency on every route, and tests attempt cross-user access on every endpoint.

### 6.3 Offer links (Task 18)

- 32-byte random token. Only its SHA-256 hash is stored, so a database leak does not expose working links.
- Expires at the response deadline. Can be answered once only. Rate-limited.
- **Accept:** typed full-name signature, plus timestamp, IP address, user agent and the SHA-256 of the exact offer PDF, all recorded in `offer_events`. This is valid under ECTA.
- **Decline:** optional reason and a courteous confirmation message.
- The founder gets an email on viewed, accepted, declined and expired.
- A POPIA notice on every offer page links to the Privacy Policy (SP/POL/2026/001).

### 6.4 Onboarding (Task 19)

On acceptance, a checklist is created automatically:

- [ ] Contractor agreement signed, with reference, version and the 12-month end date recorded
- [ ] Team Policies (SP/HR/2026/001) acknowledged
- [ ] GitHub invitation to the SaxsProjects organisation (two-factor login is enforced there)
- [ ] Company password manager access
- [ ] Banking details captured (encrypted)
- [ ] First Task Order or project assigned

The system reminds you **30 days before an agreement ends** so you can renew it or let it end on time.

### 6.5 Protected personnel records (Task 21)

- **Field-level encryption:** ID numbers and banking details are encrypted with AES-256-GCM before they reach the database. Each value stores the ID of the key that encrypted it, so keys can be rotated without downtime.
- **Least data:** these fields are optional until a payout or agreement actually needs them.
- **Masked by default:** the API returns `******1234`. Revealing the full value requires the admin's TOTP code again, and the reveal is written to the audit log.
- **Uploads:** PDF, PNG and JPG only, up to 5 MB each. File type is checked from the file's own bytes, not its name. Files are stored privately and served only through authorised endpoints.
- **Retention job (daily)** follows the Privacy Policy's retention table:
  - unsuccessful applicants are deleted after 12 months;
  - personnel records of former team members are deleted 5 years after the engagement ends;
  - financial records are kept for 5 years from the end of the financial year.
- **Data subject requests:** an admin endpoint exports everything held about a person (POPIA access request) and handles correction or deletion where the law allows.
- **Breach readiness:** a one-page incident procedure in `docs/incident-response.md` covers what to do and how to notify the Information Regulator under section 22 of POPIA.

### 6.6 Web security

- HTTPS only. Security headers: HSTS, CSP, X-Content-Type-Options, X-Frame-Options `DENY`, Referrer-Policy.
- CORS allows only `hub.saxsprojects.co.za`.
- Pydantic validates every request: lengths, formats and allowed values.
- SQLAlchemy uses parameterised queries only. No raw SQL built from strings.
- Error responses never include stack traces or internal details. Logs never contain passwords, tokens, ID numbers or banking details (a logging filter masks them).

---

## 7. Delivery Phases

Build in this order. Each phase ends with a working, tested release on staging.

| Phase | Tasks | Scope | Outcome |
|---|---|---|---|
| **0. Foundation** | 17 | Repository layout, CI, Docker Postgres, settings, health check, `.env.example`, Render and Neon staging | An empty but deployed, secure API |
| **1. Data model and auth** | 14 | Alembic `0001`, users, sessions, admin TOTP, audit log, roles | Admin can sign in securely |
| **2. Quotes, invoices and receipts** | 15 | Clients, projects, line items, gapless numbering, branded PDFs, payments, receipts, credit notes | First real quotation can be issued |
| **3. Payout engine** | 16 | Rate periods, work shares, cumulative calculation, property tests, payout statements | Payouts calculated and explained to the cent |
| **4. Offers** | 18 | Offer tokens, accept and decline, e-signature evidence, email alerts | Offers sent and answered through the Hub |
| **5. Onboarding** | 19 | Checklists, agreements with end dates, team-member login | Repeatable onboarding |
| **6. Contractor payouts** | 20 | Team-member view of shares, task orders, statements, mark as paid | Contractors can see exactly what they are owed |
| **7. Personnel records and hardening** | 21, 17 | Field encryption, masked reveal, retention job, access-request export, backups, production launch | Production-ready and POPIA-aligned |

Two practical points on timing:

- **Phases 0–3** can be finished before company registration and tested with fake data.
- **Production use of invoices waits for the registration number.** The API enforces this (section 3.3).

---

## 8. Repository Layout

```text
saxs-team-hub/
├─ backend/
│  ├─ app/
│  │  ├─ main.py              app factory, middleware, security headers
│  │  ├─ config.py            settings from environment variables
│  │  ├─ db.py                engine, session, transaction helpers
│  │  ├─ security/            passwords, tokens, totp, encryption, permissions
│  │  ├─ audit/               audit log writer
│  │  ├─ finance/             clients, quotations, invoices, payments, receipts, numbering, pdf/
│  │  ├─ payouts/             calculator.py (pure functions, no database), service.py, statements
│  │  ├─ team/                people, offers, onboarding, agreements, task_orders, personnel
│  │  ├─ email/               EmailSender interface plus SMTP and API implementations
│  │  └─ jobs/                retention, reminders, expiry
│  ├─ migrations/             Alembic
│  ├─ tests/                  unit, integration (real Postgres), property tests
│  ├─ requirements.in / requirements.txt
│  └─ Dockerfile
├─ frontend/                  React + Vite + TypeScript (later)
├─ docs/                      this plan, data model, incident-response.md, decisions/
├─ .github/workflows/         ci.yml, backup.yml, deploy.yml
├─ .env.example
└─ README.md
```

Keep `payouts/calculator.py` as **pure functions** that take numbers and return numbers. It is then easy to test thoroughly and easy to explain to a contractor.

---

## 9. Definition of Done (every phase)

- Works end to end on staging.
- Tests cover the business rules. Coverage is at least 85% on `finance/` and `payouts/`.
- ruff, mypy, pytest, pip-audit and gitleaks all pass in CI.
- No secrets or personal data in the repository or in logs.
- Alembic migration included and reversible.
- OpenAPI docs and this plan updated.

---

## 10. What Makes It Look and Work Like a Real Company

- Branded, sequentially numbered quotations, invoices, receipts and statements that carry the registration number. Drafts are clearly watermarked.
- A complete, tamper-evident record: every document hashed, every change audited, every payout explained.
- Contractor payments calculated exactly as the signed agreements say, with a statement for every payout.
- Formal offers with e-signature evidence, and repeatable onboarding with fixed agreement end dates.
- Personal information encrypted, masked, retained only as long as the Privacy Policy allows, and available to the person on request.
- Company addresses (`api.` and `hub.saxsprojects.co.za`), company email and two-factor login on every account.

---

## 11. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Render free tier sleeps or changes its limits | Health check, no in-memory state; upgrading to a paid instance needs no code change |
| Outgoing SMTP blocked on the free plan | `EmailSender` interface; HTTPS email API as fallback |
| Neon free storage limit (0.5 GB) | PDFs regenerated from data rather than stored; uploads limited to 5 MB; usage monitored |
| Lost encryption key means lost personnel data | Keys stored in Bitwarden as well as Render; key rotation supported |
| Rounding disputes on payouts | Integer cents, a single rounding step, the full calculation saved and printed on each statement |
| Invoice issued before registration | API blocks issuing until the registration number is set |
