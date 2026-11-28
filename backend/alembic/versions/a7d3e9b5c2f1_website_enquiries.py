"""v2.1: enquiries from the company website

Only adds a table, so existing data is untouched.

Revision ID: a7d3e9b5c2f1
Revises: 9c4e2a7b1d3f
Create Date: 2026-11-28 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "a7d3e9b5c2f1"
down_revision: str | Sequence[str] | None = "9c4e2a7b1d3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "enquiries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("organisation", sa.String(length=200), nullable=True),
        sa.Column("service", sa.String(length=120), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=40), server_default="website", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.db.UTCDateTime(), nullable=False),
        sa.CheckConstraint("status IN ('new', 'contacted', 'converted', 'closed')", name="ck_enquiry_status"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_enquiries_status"), "enquiries", ["status"], unique=False)
    op.create_index(op.f("ix_enquiries_created_at"), "enquiries", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_enquiries_created_at"), table_name="enquiries")
    op.drop_index(op.f("ix_enquiries_status"), table_name="enquiries")
    op.drop_table("enquiries")
