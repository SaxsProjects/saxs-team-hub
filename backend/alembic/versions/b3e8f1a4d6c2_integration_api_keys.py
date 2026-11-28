"""v2.2: API keys for other SaxsProjects systems (SAXI-OS)

Only adds a table, so existing data is untouched.

Revision ID: b3e8f1a4d6c2
Revises: a7d3e9b5c2f1
Create Date: 2026-11-28 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "b3e8f1a4d6c2"
down_revision: str | Sequence[str] | None = "a7d3e9b5c2f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.Column("last_used_at", app.db.UTCDateTime(), nullable=True),
        sa.Column("revoked_at", app.db.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("api_keys")
