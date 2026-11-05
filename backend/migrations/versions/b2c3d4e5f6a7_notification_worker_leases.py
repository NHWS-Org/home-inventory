"""Add persistent notification worker leases.

Revision ID: b2c3d4e5f6a7
Revises: a0b1c2d3e4f5
"""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("notification_events")}
    for column in (
        sa.Column("lease_token", sa.String(36)),
        sa.Column("leased_until", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("last_error", sa.String(64)),
    ):
        if column.name not in existing:
            op.add_column("notification_events", column)


def downgrade() -> None:
    for name in ("last_error", "expires_at", "leased_until", "lease_token"):
        op.drop_column("notification_events", name)
