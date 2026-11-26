# Changelog

All notable changes to the SaxsProjects Team Hub. Versions follow [Semantic Versioning](https://semver.org):
MAJOR for changes that break how people or data work, MINOR for new features, PATCH for fixes.
Each release is tagged `vX.Y.Z` and published on GitHub Releases with its packages.

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
