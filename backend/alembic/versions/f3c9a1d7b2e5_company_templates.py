"""company template library

Revision ID: f3c9a1d7b2e5
Revises: e8b2f4a6c1d9
Create Date: 2026-11-28 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

# revision identifiers, used by Alembic.
revision: str = "f3c9a1d7b2e5"
down_revision: str | Sequence[str] | None = "e8b2f4a6c1d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "company_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("archived_at", app.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=False),
        sa.CheckConstraint(
            "category IN ('letterhead', 'offer', 'contract', 'policy', 'finance', 'other')", name="ck_company_template_category"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "company_template_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("uploaded_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["company_templates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "version", name="uq_company_template_version"),
    )
    op.create_index("ix_company_template_versions_template_id", "company_template_versions", ["template_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_company_template_versions_template_id", table_name="company_template_versions")
    op.drop_table("company_template_versions")
    op.drop_table("company_templates")
