"""Prove the database-level guards work on PostgreSQL. Reads DATABASE_URL; prints only pass/fail.

Usage (from backend/): python -m scripts.check_db_guards
Writes one audit row (actor "db-guard-check"), then confirms it cannot be edited or deleted.
"""

import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.config import get_settings


def main() -> int:
    url = get_settings().database_url
    if not url.startswith("postgresql"):
        print("skip: not PostgreSQL")
        return 0
    engine = create_engine(url)
    failures = 0
    with engine.begin() as conn:
        row_id = conn.execute(
            text(
                "INSERT INTO audit_log (actor, action, entity, entity_id, at) "
                "VALUES ('db-guard-check', 'guard.check', 'system', NULL, now()) RETURNING id"
            )
        ).scalar_one()
    for label, sql in (
        ("UPDATE audit_log", "UPDATE audit_log SET actor = 'tampered' WHERE id = :id"),
        ("DELETE audit_log", "DELETE FROM audit_log WHERE id = :id"),
        ("TRUNCATE audit_log", "TRUNCATE audit_log"),
    ):
        try:
            with engine.begin() as conn:
                conn.execute(text(sql), {"id": row_id})
            print(f"FAIL: {label} was allowed")
            failures += 1
        except DBAPIError:
            print(f"ok: {label} refused")
    engine.dispose()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
