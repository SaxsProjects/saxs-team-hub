# Instructions for AI agents

Start with [docs/OVERVIEW.md](docs/OVERVIEW.md): what the Team Hub is, how it works, the repository map,
the invariants you must never break (section 10), and the safety rules for secrets.

Short version:
- Backend only (FastAPI + SQLAlchemy + Alembic + PostgreSQL) in `backend/`. Run tests and ruff before every PR.
- Money is integer cents and basis points. Issued documents and the audit log are never changed.
- The system never moves money. Members only ever see their own data.
- Never print or commit secrets. Never add AI attribution (Co-Authored-By, "Generated with") to commits, PRs or docs.
- Branch, PR, green CI, then merge. Never force-push `main`.
