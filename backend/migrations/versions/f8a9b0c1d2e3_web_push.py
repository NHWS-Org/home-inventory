"""Add session-bound Web Push subscriptions and external delivery outbox."""

from alembic import op
import sqlalchemy as sa

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "push_subscriptions" not in existing:
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("endpoint_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("p256dh", sa.String(128), nullable=False),
            sa.Column("auth", sa.String(32), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("device_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("generation", sa.String(36), nullable=False),
            sa.Column("vapid_fingerprint", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_push_subscriptions_user_session", "push_subscriptions", ["user_id", "session_id"],
        )
    if "push_deliveries" not in existing:
        op.create_table(
            "push_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("notification_events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("push_subscriptions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("generation", sa.String(36), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("available_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("leased_until", sa.DateTime()),
            sa.Column("accepted_at", sa.DateTime()),
            sa.Column("last_error", sa.String(64)),
            sa.UniqueConstraint("event_id", "subscription_id", name="uq_push_delivery_event_subscription"),
            sa.CheckConstraint(
                "status IN ('pending', 'sending', 'accepted', 'cancelled', 'failed', 'uncertain')",
                name="ck_push_delivery_status",
            ),
            sa.CheckConstraint("attempts >= 0", name="ck_push_delivery_attempts"),
        )
        op.create_index(
            "ix_push_delivery_pending", "push_deliveries", ["status", "available_at"],
        )


def downgrade() -> None:
    op.drop_table("push_deliveries")
    op.drop_table("push_subscriptions")
