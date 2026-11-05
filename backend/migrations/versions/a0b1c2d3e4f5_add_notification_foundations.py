"""Add notification event, inbox and preference foundations.

Revision ID: a0b1c2d3e4f5
Revises: 9b0c1d2e3f4a
"""

from alembic import op
import sqlalchemy as sa

revision = "a0b1c2d3e4f5"
down_revision = "9b0c1d2e3f4a"
branch_labels = None
depends_on = None


def _create_events() -> None:
    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(36), nullable=False, unique=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_notification_events_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_notification_events_attempts"),
    )
    op.create_index(
        "ix_notification_events_pending", "notification_events", ["status", "available_at"],
    )


def _create_inbox() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id", sa.Integer(),
            sa.ForeignKey("notification_events.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime()),
        sa.UniqueConstraint("event_id", "user_id", name="uq_notifications_event_user"),
    )
    op.create_index(
        "ix_notifications_user_unread", "notifications", ["user_id", "read_at", "id"],
    )


def _create_preferences() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("include_own_actions", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("data_ins", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("data_mod", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("user_ins", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("user_mod", sa.Integer(), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("user_id", "event_type", name="uq_notification_preferences_user_event"),
        sa.CheckConstraint(
            "event_type IN ('inventory_shared', 'item_quantity_changed', 'checklist_completed')",
            name="ck_notification_preferences_event_type",
        ),
    )


def upgrade() -> None:
    # The Docker entrypoint runs Base.metadata.create_all before Alembic.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name, create in (
        ("notification_events", _create_events),
        ("notifications", _create_inbox),
        ("notification_preferences", _create_preferences),
    ):
        if name not in existing:
            create()


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_table("notifications")
    op.drop_table("notification_events")
