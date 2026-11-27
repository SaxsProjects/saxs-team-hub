"""trusted devices and passkeys

Revision ID: e8b2f4a6c1d9
Revises: d7a4c2e9f1b3
Create Date: 2026-11-27 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

# revision identifiers, used by Alembic.
revision: str = "e8b2f4a6c1d9"
down_revision: str | Sequence[str] | None = "d7a4c2e9f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "trusted_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("failed_unlocks", sa.Integer(), nullable=False),
        sa.Column("revoked_at", app.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trusted_devices_user_id"), "trusted_devices", ["user_id"], unique=False)
    op.create_index(op.f("ix_trusted_devices_token_hash"), "trusted_devices", ["token_hash"], unique=True)
    op.create_table(
        "passkeys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", app.db.UTCDateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["trusted_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_id"),
    )
    op.create_index(op.f("ix_passkeys_user_id"), "passkeys", ["user_id"], unique=False)
    op.create_index(op.f("ix_passkeys_device_id"), "passkeys", ["device_id"], unique=False)
    op.create_table(
        "webauthn_challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("used_at", app.db.UTCDateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["trusted_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_webauthn_challenges_device_id"), "webauthn_challenges", ["device_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_webauthn_challenges_device_id"), table_name="webauthn_challenges")
    op.drop_table("webauthn_challenges")
    op.drop_index(op.f("ix_passkeys_device_id"), table_name="passkeys")
    op.drop_index(op.f("ix_passkeys_user_id"), table_name="passkeys")
    op.drop_table("passkeys")
    op.drop_index(op.f("ix_trusted_devices_token_hash"), table_name="trusted_devices")
    op.drop_index(op.f("ix_trusted_devices_user_id"), table_name="trusted_devices")
    op.drop_table("trusted_devices")
