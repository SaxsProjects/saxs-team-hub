# Team Hub backend

FastAPI + SQLAlchemy + Alembic, PostgreSQL in production (Neon), SQLite for local development and tests.
Interactive API docs are at `/docs` when `ENVIRONMENT` is not `production`.

## API overview

| Area | Endpoints | Who |
|---|---|---|
| Auth | `POST /api/auth/login` · `POST /api/auth/set-password` (invite or reset link) · `POST /api/auth/forgot-password` · `POST /api/auth/change-password` (returns a new token, signs out other sessions) · `GET /api/auth/me` · `POST /api/auth/2fa/setup` · `POST /api/auth/2fa/enable` | everyone |
| People | `GET/POST /api/people` · `GET/PATCH/DELETE /api/people/{id}` (a rate change takes `rate_bp`, `rate_review_note` and optional `rate_effective_from`; `fee_terms` is `standard` or `deferred`) · `GET /api/people/{id}/rates` · `POST /api/people/{id}/stage` · `PUT/GET /api/people/{id}/sensitive` · `GET/POST /api/people/{id}/documents` · `POST /api/people/{id}/invite` (new set-password link) · `POST /api/people/{id}/access` (`{"active": false}` at offboarding signs them out everywhere) | admin |
| Offers | `GET/POST /api/offers` · `GET/PATCH /api/offers/{id}` · `POST /api/offers/{id}/pdf` · `POST /api/offers/{id}/send` · `POST /api/offers/{id}/revoke` · `GET /api/pipeline` | admin |
| Candidate link | `GET /api/public/offers/{token}` · `GET …/{token}/pdf` · `POST …/{token}/accept` · `POST …/{token}/decline` | anyone with the link |
| Onboarding | `GET /api/people/{id}/onboarding` · `PATCH /api/onboarding/{item}` | admin |
| Projects & payouts | `GET/POST /api/projects` · `GET/PATCH /api/projects/{id}` · `PUT /api/projects/{id}/contributors` · `DELETE …/contributors/{person}` · `POST …/lock` · `POST …/costs` · `POST …/payments` · `GET /api/payouts` (`?unpaid=true`, `?requested=true`) · `POST /api/payouts/{id}/paid` | admin |
| Task Orders | `GET/POST /api/task-orders` (`?status_filter=`, `?person_id=`, `?review_overdue=true`) · `GET/PATCH /api/task-orders/{id}` (PATCH only before the contractor confirms) · `POST …/accept` (creates the fee payout) · `POST …/request-changes` · `POST …/cancel` | admin |
| Statements | `GET /api/payouts/{id}/statement.pdf` (revenue share or task fee) | admin, or the contributor it belongs to |
| Clients | `GET/POST /api/clients` · `GET/PATCH /api/clients/{id}` | admin |
| Quotations | `GET/POST /api/quotations` · `GET/PATCH/DELETE /api/quotations/{id}` (drafts only) · `POST …/issue` · `POST …/accept` (creates the project) · `POST …/decline` · `GET …/pdf` | admin |
| Invoices | `GET/POST /api/invoices` (from an accepted quotation, optionally `portion_percent` for a deposit) · `GET/PATCH/DELETE /api/invoices/{id}` (drafts only) · `POST …/issue` · `POST …/payments` (issues a receipt, triggers payouts) · `POST …/credit-notes` · `GET …/receipts` · `GET …/credit-notes` · `GET …/pdf` | admin |
| Receipts & credit notes | `GET /api/receipts/{id}/pdf` · `GET /api/credit-notes/{id}/pdf` | admin |
| Finance overview | `GET /api/finance/readiness` (what is still missing, never the values) · `GET /api/finance/summary` | admin |
| Team member | `GET /api/me/profile` · `GET/PATCH /api/me/onboarding` · `PUT/GET /api/me/sensitive` · `GET /api/me/projects` · `GET /api/me/payouts` · `POST /api/me/payouts/{id}/request-payment` (once due; reminder allowed after 3 days; emails the founder) · `GET /api/me/rates` · `GET /api/me/task-orders` · `POST /api/me/task-orders/{id}/confirm` · `POST …/decline` · `POST …/submit` · `GET /api/me/documents` · `GET /api/documents/{id}` | the member, own data only |
| System | `GET /api/health` · `GET /api/audit` (admin) · `POST /api/jobs/daily` (`X-Jobs-Token`) | |

## Pages for email links

People who click links in emails don't need any frontend: the backend serves simple, accessible HTML pages (no JavaScript) that use exactly the same rules as the API.

| Page | Who | What |
|---|---|---|
| `/offer/<token>` | candidate | Read the offer, open the PDF, accept by typing their full name, or decline with an optional reason |
| `/set-password?token=…` | new team member | Choose a password from the invite link (valid 7 days) |
| `/forgot-password` → `/reset-password?token=…` | team member / founder | Request and use a 1-hour reset link |

Set `FRONTEND_URL` to the API's own URL until the React frontend exists, so email links point at these pages. The founder can manage everything else from the interactive API docs at `/docs` (set `ENABLE_API_DOCS=true` in production; every admin action still needs a signed-in admin with two-factor on).

## Sessions

Sessions are 60-minute tokens. Changing or resetting a password, or turning a member's access off, signs that account out everywhere: tokens issued before that moment are rejected.

## How the rules from the plan are enforced

- **Offer links:** 256-bit random tokens; only the SHA-256 hash is stored. A link expires at 23:59 SAST on the deadline, can be answered once, and stops working when revoked or re-sent.
- **Proof of acceptance:** the candidate must tick the confirmation box and type their full name exactly as on the offer. The response stores the timestamp, IP address, browser and a hash of the exact offer version (role, reference, deadline, message and the proposal PDF's SHA-256). An acceptance-record PDF is generated, stored and emailed to the candidate.
- **Pipeline:** `draft → sent → viewed → accepted / declined / expired → agreement_signed → onboarded`. Every change is written to the append-only audit log.
- **Notifications:** the founder (`ADMIN_NOTIFY_EMAIL`) is emailed when an offer is viewed (first time), accepted, declined or expires. The candidate gets a confirmation after responding. Accepting also creates their team-member account and emails a 7-day set-password link.
- **Onboarding:** the 7-item checklist from the plan is created on acceptance. Members can tick "channel joined" and "standards read" themselves; the founder confirms the rest. Saving banking details or uploading the signed agreement ticks those items automatically.
- **Payouts:** money is integer cents; rates and shares are basis points. Shares lock when the project moves to `in_progress` or the first client payment is recorded. Each client payment creates payouts for what each contributor has *newly* earned:
  `earned_to_date = max(0, received_to_date − costs_to_date) × rate × share`, `payout = earned_to_date − already_paid`.
  This handles instalments, never claws back, and makes later costs reduce later payouts. Payouts are due 7 days after the client payment.
- **Rate history:** a rate change (15% ↔ 20%) needs a written-review note and is stored in `rate_periods` with the date it applies from (default today; it can be dated ahead or back to the review's date). The developer agreement says the 20% rate applies *from the date* of the written review and that each instalment is shared as it is received, so **each instalment is shared at the rate in force on the day it was received**. Direct costs are set against the earliest instalments first, and everything is rounded once:
  `slice_j = max(0, R_j − C) − max(0, R_(j−1) − C)`, `earned_to_date = Σ slice_j × rate_j × share`.
  With one rate throughout this is the same as the formula above. A review recorded late but dated earlier pays the difference on the next instalment; nothing is ever clawed back. The statement lists each instalment's rate when a project was paid at more than one rate.
- **Task Orders (task-fee contractors):** `proposed → confirmed → submitted → accepted`, or `declined` by the contractor, or `cancelled` by the founder before submission; `request-changes` sends a submission back with a note. A Task Order is numbered `SP-TO-YYYY-NNN`, can be edited only until the contractor confirms it, and copies the person's `fee_terms`. Accepting it creates a `task_fee` payout with its own `SP-PS` statement:
  - `standard` terms: due 7 days after acceptance.
  - `deferred` terms (agreements SP/ICA/2026/004 and 005): a task accepted before the First Client Payment waits (no due date) and becomes due 30 days after that payment; a task accepted on or after it is due 7 days after acceptance. The First Client Payment is the earliest project payment or invoice receipt; recording it releases waiting fees automatically.
  - The founder reviews a submission within 5 days. Late reviews are flagged (`review_overdue`) and emailed by the daily job.
- **POPIA:** banking and ID details are encrypted (Fernet) and masked unless the founder explicitly reveals them (which is audited). Every offer page shows a privacy notice. The daily job deletes candidates who declined or let the offer expire after `DECLINED_RETENTION_DAYS` (365). The audit log stores ids, not names or contact details.
- **Security:** argon2 password hashing, 60-minute JWT sessions, TOTP two-factor required for the admin in production, rate limiting on login and offer links, CORS allow-list, security headers (HSTS in production), PDF-only uploads up to 10 MB (checked by content, not file name). In production the app refuses to start without strong secrets, PostgreSQL and SMTP.
- **Documents:** stored in the database with SHA-256 and a version number, so signed records survive redeploys.

## Daily jobs

`python -m app.cli daily-jobs` or `POST /api/jobs/daily` with `X-Jobs-Token`. It expires overdue offers (and emails the founder, which is the "day after the deadline" reminder), emails a list of payouts that are due (revenue share and task fees) and of task reviews past their 5-day deadline, expires quotations past their validity date, emails a list of overdue invoices, and applies POPIA retention. `.github/workflows/daily-jobs.yml` calls it every morning once the `TEAM_HUB_API_URL` and `TEAM_HUB_JOBS_TOKEN` repository secrets are set.

## Finance: quotations, invoices, receipts and credit notes

- **Numbers** (`SP-Q-`, `SP-INV-`, `SP-R-`, `SP-CN-`, `SP-PS-YYYY-NNN`) come from `document_sequences`. The row is locked while a number is taken, inside the same transaction as the document, so numbers never repeat and a failed request never leaves a gap. The counter restarts each year. `tests/test_numbering_postgres.py` issues 50 invoices in parallel against PostgreSQL to prove it.
- **Drafts** can be edited or deleted. They have no number, their PDF is a preview with a DRAFT watermark, and they are never signed.
- **Issuing** assigns the number, renders the PDF once, and stores it in `documents` with its SHA-256. Later downloads return exactly those bytes. Issued documents cannot be changed (HTTP 409): an invoice is corrected with a credit note.
- **Money** is integer cents. VAT is added only once `COMPANY_VAT_NUMBER` is set (then invoices say TAX INVOICE). Payouts are calculated on money received excluding VAT.
- **Payments** on an invoice issue a receipt automatically and, when the invoice belongs to a project, record the client payment that creates contributor payouts (the same rule as `POST /projects/{id}/payments`).
- **Deposits:** `POST /api/invoices {"quotation_id": 1, "portion_percent": 50}` bills 50%; a later `{"quotation_id": 1}` bills whatever is left. A quotation can never be invoiced for more than its total.

### Signed documents

The director's signature is printed on **issued quotations, receipts, credit notes, payout statements and offer acceptance records**. Invoices carry the banking details instead, and drafts are never signed.

The signature image is never stored in the repository. Set it as configuration:

| Variable | Purpose |
|---|---|
| `SIGNATURE_IMAGE_PATH` | Path to a PNG or JPEG (max 1 MB). On Render, add a **Secret File** named `signature.png` and set this to `/etc/secrets/signature.png` |
| `SIGNATURE_IMAGE_BASE64` | Alternative: the image as base64 |
| `SIGNATORY_NAME`, `SIGNATORY_TITLE` | Printed under the signature (title defaults to Director) |

Production refuses to start without the signature, and the app checks the image at startup. Quotations, receipts and credit notes cannot be issued until it is set.

### Company details

| Variable | Notes |
|---|---|
| `COMPANY_LEGAL_NAME`, `COMPANY_REGISTRATION_NUMBER`, `COMPANY_VAT_NUMBER` | Invoices cannot be issued until the registration number is set |
| `COMPANY_ADDRESS` | Lines separated by `|` |
| `COMPANY_EMAIL`, `COMPANY_PHONE`, `COMPANY_WEBSITE` | |
| `COMPANY_BANK_NAME`, `COMPANY_BANK_ACCOUNT_NAME`, `COMPANY_BANK_ACCOUNT_NUMBER`, `COMPANY_BANK_BRANCH_CODE`, `COMPANY_BANK_ACCOUNT_TYPE` | Never committed. Invoices cannot be issued until name, account number and branch code are set |
| `QUOTE_VALID_DAYS` (30), `INVOICE_DUE_DAYS` (7), `DEPOSIT_PERCENT` (50), `VAT_RATE_BP` (1500) | Defaults in brackets |

These variables are the starting values. The founder can change all of them except the trading name and the
signature image in **Settings → Company** (`GET/PUT /api/company`, `app/company.py`): founder only, two-factor
required, the current password for any banking change, every change audited (account numbers masked) and a bank
change emailed to `ADMIN_NOTIFY_EMAIL` at once. Saved values are stored encrypted in `company_profile` and win
over the variables. `GET /api/finance/readiness` lists anything still missing.

`GET /api/audit?scope=workspace` returns business activity only; `scope=account` returns sign-ins, security
events and personal settings (shown in Settings → Security instead of Audit history).

## Client IP addresses and sign-in limits

- `X-Forwarded-For` is read from the **right**: each proxy appends the address it received the request from, so only the last `TRUSTED_PROXY_HOPS` entries (Render: 1) were written by our infrastructure. Anything to the left was sent by the caller and is ignored. Missing or invalid values fall back to the connecting address. uvicorn runs with `--no-proxy-headers`, so it never trusts the header blindly.
- If the IP recorded on offer acceptances ever shows a Render-internal address after deploying, raise `TRUSTED_PROXY_HOPS` to 2.
- Sign-in has two failure limits on top of the per-IP request limit, and neither can be dodged by changing IP:
  - **Account + IP** (`LOGIN_FAILURES_PER_ACCOUNT_IP`, 10): that IP is locked out of that account for `LOGIN_LOCKOUT_MINUTES` (15). An attacker only locks themselves out, never the owner.
  - **Account, all IPs** (`LOGIN_FAILURES_PER_ACCOUNT`, 50): stops guessing spread over many IPs. While it is hit, only the correct password **and** two-factor code together can sign in, so the owner of a 2FA account (every admin in production) is never locked out. Accounts without 2FA wait for it to expire.
  - **Wrong two-factor codes, all IPs** (`TOTP_FAILURES_PER_ACCOUNT`, 10): whoever is guessing already has the password, so every sign-in to the account is refused until the lock expires (even a correct code), and the owner is emailed to change their password.
  - Locked answers are identical for every email, existing or not, so they reveal nothing.
- IPv6 addresses are grouped by /64 for all of these limits, because one connection usually has a whole /64 to rotate through. IPv4 addresses written in IPv6 form (IPv4-mapped, NAT64, 6to4, Teredo) are limited by their real IPv4 address, so they never share one key.
- Each sign-in attempt reserves its slot in the counters atomically **before** the slow checks (password hashing, database) and gives it back if that step succeeds. A burst of parallel requests cannot slip past a limit, and no lock is ever held while anything slow runs, so hammering one account cannot stall the server. The two-factor alert email is sent on its own thread.
- At most `RESET_EMAILS_PER_ACCOUNT_PER_HOUR` (3) password-reset emails are sent per account; the response is always the same.
- These counters are in memory: correct for one Render instance. Move them to the database or Redis before running more than one. Memory is bounded at 10,000 keys per counter; when full, expired and low-count keys are dropped first and active lockouts are never dropped, so flooding cannot clear a lock.


## Screens API (Phase B backend)

One request per screen, aggregated in the database:

- `GET /api/dashboard` (founder): payouts unpaid / due now / due in 7 days / waiting for the First Client Payment / payment requested / paid this year; invoices outstanding and overdue; quotations awaiting an answer; Task Orders by status and overdue reviews; people by status; money received this year.
- `GET /api/me/overview` (team member): current rate, amount owed, due now, how many payouts can be requested, next due date, amount waiting for the First Client Payment, paid this year, Task Orders to confirm / in progress / awaiting review, open onboarding items.
- `GET /api/payment-list.csv` (founder, `?requested_only=true` optional): unpaid payouts that are due, to pay from in the banking app. Deliberately without bank account numbers (beneficiaries live in the bank); cells are protected against spreadsheet formula injection; every export is audited.

## Backups

`scripts/backup.py` writes an encrypted, authenticated logical backup (gzip JSON + Fernet), taken from one database snapshot. `verify` checks a file without a database; `restore` loads into an empty database migrated to the same revision, in one transaction, and moves the id sequences past the restored rows. CI restores a backup into a fresh PostgreSQL database on every change. See `docs/deploy.md` for the monthly routine.
