"""append-only audit log

The audit log is evidence: who changed what, and when. On PostgreSQL a trigger now refuses any
UPDATE, DELETE or TRUNCATE of audit rows, whoever the database user is, so a bug or a stolen
app password cannot quietly rewrite history. SQLite (tests, local development) is unchanged.

Revision ID: 9d1e5a7c2b40
Revises: 7c3684773143
Create Date: 2026-11-26 10:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "9d1e5a7c2b40"
down_revision: str | Sequence[str] | None = "7c3684773143"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_is_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_update_or_delete BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_is_append_only()"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_or_delete ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_is_append_only()")
