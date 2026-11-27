"""company details edited in the app

Revision ID: d7a4c2e9f1b3
Revises: c3e8f1a2d4b6
Create Date: 2026-11-27 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

# revision identifiers, used by Alembic.
revision: str = "d7a4c2e9f1b3"
down_revision: str | Sequence[str] | None = "c3e8f1a2d4b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "company_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data_enc", sa.Text(), nullable=False),
        sa.Column("updated_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("company_profile")
