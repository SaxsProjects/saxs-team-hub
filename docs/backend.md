# Team Hub backend

FastAPI + SQLAlchemy + Alembic, PostgreSQL in production (Neon), SQLite for local development and tests.
Interactive API docs are at `/docs` when `ENVIRONMENT` is not `production`.

## API overview

| Area | Endpoints | Who |
|---|---|---|
| Auth | `POST /api/auth/login` · `POST /api/auth/set-password` · `POST /api/auth/change-password` · `GET /api/auth/me` · `POST /api/auth/2fa/setup` · `POST /api/auth/2fa/enable` | everyone |
| People | `GET/POST /api/people` · `GET/PATCH/DELETE /api/people/{id}` · `POST /api/people/{id}/stage` · `PUT/GET /api/people/{id}/sensitive` · `GET/POST /api/people/{id}/documents` | admin |
| Offers | `GET/POST /api/offers` · `GET/PATCH /api/offers/{id}` · `POST /api/offers/{id}/pdf` · `POST /api/offers/{id}/send` · `POST /api/offers/{id}/revoke` · `GET /api/pipeline` | admin |
| Candidate link | `GET /api/public/offers/{token}` · `GET …/{token}/pdf` · `POST …/{token}/accept` · `POST …/{token}/decline` | anyone with the link |
| Onboarding | `GET /api/people/{id}/onboarding` · `PATCH /api/onboarding/{item}` | admin |
| Projects & payouts | `GET/POST /api/projects` · `GET/PATCH /api/projects/{id}` · `PUT /api/projects/{id}/contributors` · `DELETE …/contributors/{person}` · `POST …/lock` · `POST …/costs` · `POST …/payments` · `GET /api/payouts` · `POST /api/payouts/{id}/paid` | admin |
| Statements | `GET /api/payouts/{id}/statement.pdf` | admin, or the contributor it belongs to |
| Team member | `GET /api/me/profile` · `GET/PATCH /api/me/onboarding` · `PUT/GET /api/me/sensitive` · `GET /api/me/projects` · `GET /api/me/payouts` · `GET /api/me/documents` · `GET /api/documents/{id}` | the member, own data only |
| System | `GET /api/health` · `GET /api/audit` (admin) · `POST /api/jobs/daily` (`X-Jobs-Token`) | |

## How the rules from the plan are enforced

- **Offer links:** 256-bit random tokens; only the SHA-256 hash is stored. A link expires at 23:59 SAST on the deadline, can be answered once, and stops working when revoked or re-sent.
- **Proof of acceptance:** the candidate must tick the confirmation box and type their full name exactly as on the offer. The response stores the timestamp, IP address, browser and a hash of the exact offer version (role, reference, deadline, message and the proposal PDF's SHA-256). An acceptance-record PDF is generated, stored and emailed to the candidate.
- **Pipeline:** `draft → sent → viewed → accepted / declined / expired → agreement_signed → onboarded`. Every change is written to the append-only audit log.
- **Notifications:** the founder (`ADMIN_NOTIFY_EMAIL`) is emailed when an offer is viewed (first time), accepted, declined or expires. The candidate gets a confirmation after responding. Accepting also creates their team-member account and emails a 7-day set-password link.
- **Onboarding:** the 7-item checklist from the plan is created on acceptance. Members can tick "channel joined" and "standards read" themselves; the founder confirms the rest. Saving banking details or uploading the signed agreement ticks those items automatically.
- **Payouts:** money is integer cents; rates and shares are basis points. Shares lock when the project moves to `in_progress` or the first client payment is recorded. Rates are 15% or 20%, and changing to 20% requires a written-review note. Each client payment creates payouts for what each contributor has *newly* earned:
  `earned_to_date = max(0, received_to_date − costs_to_date) × rate × share`, `payout = earned_to_date − already_paid`.
  This handles instalments, never claws back, and makes later costs reduce later payouts. Payouts are due 7 days after the client payment.
- **POPIA:** banking and ID details are encrypted (Fernet) and masked unless the founder explicitly reveals them (which is audited). Every offer page shows a privacy notice. The daily job deletes candidates who declined or let the offer expire after `DECLINED_RETENTION_DAYS` (365). The audit log stores ids, not names or contact details.
- **Security:** argon2 password hashing, 60-minute JWT sessions, TOTP two-factor required for the admin in production, rate limiting on login and offer links, CORS allow-list, security headers (HSTS in production), PDF-only uploads up to 10 MB (checked by content, not file name). In production the app refuses to start without strong secrets, PostgreSQL and SMTP.
- **Documents:** stored in the database with SHA-256 and a version number, so signed records survive redeploys.

## Daily jobs

`python -m app.cli daily-jobs` or `POST /api/jobs/daily` with `X-Jobs-Token`. It expires overdue offers (and emails the founder, which is the "day after the deadline" reminder), emails a list of payouts that are due, and applies POPIA retention. `.github/workflows/daily-jobs.yml` calls it every morning once the `TEAM_HUB_API_URL` and `TEAM_HUB_JOBS_TOKEN` repository secrets are set.
