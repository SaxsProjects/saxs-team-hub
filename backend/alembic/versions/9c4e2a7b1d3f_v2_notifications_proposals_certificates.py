"""v2.0: client kinds and VAT numbers, invoice follow-ups, notifications, proposals and certificates

Only adds tables and columns (every new column has a default), so existing rows stay as they are and
the previous release keeps working against the upgraded database.

Revision ID: 9c4e2a7b1d3f
Revises: f3c9a1d7b2e5
Create Date: 2026-11-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

# revision identifiers, used by Alembic.
revision: str = "9c4e2a7b1d3f"
down_revision: str | Sequence[str] | None = "f3c9a1d7b2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLIENT_KINDS = "kind IN ('company', 'sole_proprietor', 'individual', 'npo', 'government', 'other')"
CERTIFICATE_KINDS = (
    "kind IN ('completion', 'achievement', 'appreciation', 'participation', 'recognition', 'training', 'service',"
    " 'project', 'partnership', 'custom')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("clients") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=24), server_default="company", nullable=False))
        batch.add_column(sa.Column("vat_number", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("reminders_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
        batch.create_check_constraint("ck_client_kind", CLIENT_KINDS)

    with op.batch_alter_table("invoices") as batch:
        batch.add_column(sa.Column("reminder_stage", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("last_reminded_at", app.db.UTCDateTime(timezone=True), nullable=True))

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("read_at", app.db.UTCDateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("introduction", sa.Text(), nullable=True),
        sa.Column("need", sa.Text(), nullable=True),
        sa.Column("solution", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("timeline", sa.Text(), nullable=True),
        sa.Column("why_us", sa.Text(), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("vat_rate_bp", sa.Integer(), nullable=False),
        sa.Column("subtotal_cents", sa.Integer(), nullable=False),
        sa.Column("vat_cents", sa.Integer(), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("quotation_id", sa.Integer(), nullable=True),
        sa.Column("pdf_document_id", sa.Integer(), nullable=True),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'issued', 'accepted', 'declined', 'expired')", name="ck_proposal_status"),
        sa.CheckConstraint("total_cents >= 0 AND subtotal_cents >= 0 AND vat_cents >= 0", name="ck_proposal_amounts"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quotation_id"], ["quotations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pdf_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )
    op.create_index("ix_proposals_client_id", "proposals", ["client_id"])
    op.create_index("ix_proposals_status", "proposals", ["status"])

    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("subtitle", sa.String(length=80), nullable=True),
        sa.Column("lead", sa.String(length=200), nullable=False),
        sa.Column("recipient_name", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("place", sa.String(length=120), nullable=False),
        sa.Column("verify_code", sa.String(length=32), nullable=False),
        sa.Column("revoked_at", app.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=300), nullable=True),
        sa.Column("pdf_document_id", sa.Integer(), nullable=False),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=False),
        sa.Column("issued_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.CheckConstraint(CERTIFICATE_KINDS, name="ck_certificate_kind"),
        sa.ForeignKeyConstraint(["pdf_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
        sa.UniqueConstraint("verify_code"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("certificates")
    op.drop_index("ix_proposals_status", table_name="proposals")
    op.drop_index("ix_proposals_client_id", table_name="proposals")
    op.drop_table("proposals")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    with op.batch_alter_table("invoices") as batch:
        batch.drop_column("last_reminded_at")
        batch.drop_column("reminder_stage")
    with op.batch_alter_table("clients") as batch:
        batch.drop_constraint("ck_client_kind", type_="check")
        batch.drop_column("reminders_enabled")
        batch.drop_column("vat_number")
        batch.drop_column("kind")
