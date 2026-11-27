# Changelog

All notable changes to the SaxsProjects Team Hub. Versions follow [Semantic Versioning](https://semver.org):
MAJOR for changes that break how people or data work, MINOR for new features, PATCH for fixes.
Each release is tagged `vX.Y.Z` and published on GitHub Releases with its packages.

## [1.7.0] - 2026-11-27

### Added
- **Stay signed in on your phone.** "Keep me signed in on this device" trusts a phone or computer after one full
  sign-in. After that the app opens with **Welcome back** and your email already filled in: unlock with Face ID,
  your fingerprint or face, or Windows Hello (passkeys), or your password alone. No two-factor code.
- **Locks after 5 minutes in the background**, and opens again with the fingerprint, face or password.
- **Trusted devices** in Settings > Security: see each device and when it was last used, remove any of them, and
  set up fingerprint or face unlock. A new trusted device sends you an email.
- **Android app:** passkeys work inside the app (the website names the app in `/.well-known/assetlinks.json`).

### Changed
- **Forgot password now asks for your two-factor code** (when two-factor is on) as well as the email link, and a
  reset removes every trusted device.
- Trust ends after 90 days without use, or after 5 wrong passwords on the device; then the full sign-in is needed.

## [1.6.0] - 2026-11-27

### Added
- **See every document before it goes anywhere.** Quotations, invoices, receipts, credit notes, payout statements,
  team documents and the payment list now open in a preview first, with zoom; Download saves exactly what you saw.
- **Preview before issuing.** Draft quotations and invoices show the draft PDF with "Issue" as the last step.
  Recording a payment shows the receipt, and a credit note shows the credit note, before either is numbered,
  signed or saved (`POST /api/invoices/{id}/payments/preview` and `/credit-notes/preview` save nothing).
- **Preview before sending an offer.** The founder sees the proposal PDF and the exact email the candidate will
  get (`POST /api/offers/email-preview`) before it is sent. `GET /api/offers/{id}/pdf` opens an offer's attached proposal.
- **Downloads in the Android app.** The app saves documents to Downloads/Team Hub (it couldn't download before).

### Fixed
- "View statement" downloaded the file instead of showing it.
- A dialog opened from another dialog: Escape now closes only the top one, and the page scrolls again once all are closed.

## [1.5.0] - 2026-11-27

### Added
- **Company details in Settings**: edit the registered name, registration and VAT numbers, address, contact details,
  signatory and banking details from the app. Needs two-factor and your password; every change is
  emailed to you at once and recorded with the account number masked. Documents use the saved details.
- **Search that finds things**: people, projects, Task Orders, clients, invoices, quotations and payout statements,
  with arrow keys and Enter; each result opens the exact record. On phones, search opens from a magnifier button.
- **Settings → Security** lists recent sign-ins and security events.

### Changed
- Audit history, the bell and recent activity show workspace activity only; sign-ins and account events moved to
  Settings → Security.
- The bell's dot means new activity since you last opened it, and each item opens the record it is about.
- Notification switches save as soon as they are flipped.
- Phones: stats sit two per row so lists start on the first screen; wide tables scroll inside their card and amounts
  never break across lines; slightly larger secondary text.

### Fixed
- Dialogs take keyboard focus when they open, keep Tab inside, close on Escape and give focus back; long dialogs
  scroll instead of running off the screen.

## [1.4.2] - 2026-11-27

### Fixed
- Audit history, the bell and recent activity now name every event in plain English (for example
  "Password reset requested" and "Old sign-in pass reused; session ended"); security events are marked amber.
- Notification switches that are off are easier to see.
- Founder settings show the founder's name instead of "Founder".

## [1.4.1] - 2026-11-27

### Added
- Founder settings: switch each founder email on or off (offer updates, Task Order reviews, payout reminders,
  invoice reminders) and save with **Save changes**. Every change is recorded in the audit history.

## [1.4.0] - 2026-11-27

### Added
- Founder screens, built to the Figma design and matching the team member screens:
  - **Team & offers**: team stats, the offer pipeline (sent, viewed, accepted), the team directory, add a person,
    and draft or send an offer with its proposal PDF.
  - **Member profile**: onboarding checklist with founder confirmations, stage moves, masked banking details with an
    audited reveal, written rate reviews and the member's documents.
  - **Projects** and **project detail**: client money, direct costs and contributors per project; add contributors with
    work shares, lock shares, record client payments and costs, and download the project's quotations and invoices.
  - **Task Orders**: the register with filters and paging, review a submission (accept or request changes),
    cancel open work, and create a new Task Order.
  - **Client finance**: clients, quotations, invoices, receipts and credit notes, each with totals, search and filters;
    issue documents, record acceptance, invoice a quotation in full or as a deposit, record payments and issue credit notes.
  - **Payouts**: due now, requested, upcoming, deferred and paid; record the EFT reference, view statements,
    the deferred fee schedule and the payment list export.
  - **Audit history**: search and filter every event, see its full record and export the filtered events as CSV.
  - **Settings**: profile, company readiness for invoicing, two-factor setup, password change and the founder emails.

### Changed
- Founder screens load on demand, so team members download less.

## [1.3.0] - 2026-11-27

### Added
- Team member screens, built to the Figma design:
  - **My projects**: each project's client money, costs, rate × work share and next payout, project documents and rate history.
  - **My Task Orders**: filter by status, confirm or decline new work, submit a delivery link and note for review.
  - **My payouts**: totals, due/upcoming/paid filters, the full calculation behind each amount, payout status,
    request payment and download the statement PDF.
  - **My documents**: agreements and statements in one searchable list with PDF download.
  - **Onboarding**: progress, the checklist, and how to finish each step; members tick the steps they own.
  - **Settings**: profile, banking details (stored encrypted, shown masked), change password and sign out.

## [1.2.1] - 2026-11-26

### Changed
- Web app built with Vite 8 and React Router 8; tests run on Vitest 5 with jest-dom 8.
- CI and backups use the current GitHub Actions (checkout 7, setup-python 7, setup-java 6, upload-artifact 7).
- Android release APKs are now built and signed by the release workflow itself.

## [1.2.0] - 2026-11-26

### Added
- Android app (`mobile/`, package `za.co.saxsprojects.teamhub`): opens the live Team Hub at
  hub.saxsprojects.co.za, with the SaxsProjects icon and splash screen and an offline page.
  Signed release APK attached to each GitHub Release (`saxs-team-hub-android-X.Y.Z.apk`).
- The web app is live at https://hub.saxsprojects.co.za.

## [1.1.0] - 2026-11-26

### Added
- Team Hub web app (`frontend/`): sign-in with two-factor, the navy sidebar and top bar, the founder's
  Business overview and the team member's My workspace, connected to the live API.
- Company logo throughout: sidebar, sign-in pages, browser tab and installable app icons.
- Version shown in the app and in `/api/health`; one version for the whole product (`VERSION`).

### Changed
- Sign-ins stay alive while people work: 15-minute access passes renewed in the background, ended after
  30 idle minutes, after 12 hours (8 for the founder), on sign-out and on password changes.
- The API is to be served at `api.saxsprojects.co.za` and the app at `hub.saxsprojects.co.za`.

### Security
- Renewal cookie is HttpOnly, Secure, SameSite=Strict and host-only; reused tokens end the session.
- Web app security headers: CSP, HSTS, frame, referrer and permissions policies.

## [1.0.0] - 2026-11-26

### Added
- Team Hub API live on Render with Neon PostgreSQL: people and offers with signed PDFs, online offer
  acceptance, onboarding, projects and revenue-share payouts, Task Orders, quotations, invoices,
  receipts, payment requests and the payment list, audit history, profile pictures, encrypted
  backups, daily jobs, and email through Resend.
