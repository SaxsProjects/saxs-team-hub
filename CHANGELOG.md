# Changelog

All notable changes to the SaxsProjects Team Hub. Versions follow [Semantic Versioning](https://semver.org):
MAJOR for changes that break how people or data work, MINOR for new features, PATCH for fixes.
Each release is tagged `vX.Y.Z` and published on GitHub Releases with its packages.

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
