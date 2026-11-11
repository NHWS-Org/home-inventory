"""Replace rule-based notification data with personal event defaults.

Old event semantics are not translatable: discard inbox/outbox work, but
preserve device sessions and push subscriptions.
"""

from alembic import op
import sqlalchemy as sa

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    # Delete dependants first, including ambiguous/in-flight old external deliveries.
    for name in ("push_deliveries", "notifications", "notification_events", "notification_preferences"):
        if name in tables:
            bind.execute(sa.text(f"DELETE FROM {name}"))
    if "notification_rules" in tables:
        op.drop_table("notification_rules")
    with op.batch_alter_table("notification_preferences") as batch:
        batch.drop_constraint("ck_notification_preferences_event_type", type_="check")
        batch.create_check_constraint(
            "ck_notification_preferences_event_type",
            "event_type IN ('item_quantity_changed', 'item_updated', 'inventory_updated')",
        )
        batch.alter_column("in_app_enabled", existing_type=sa.Boolean(), server_default="0")
    # Omit the retired column so ORM bootstrap works with both schema versions.
    preferences = sa.table(
        "notification_preferences",
        sa.column("user_id", sa.Integer()), sa.column("event_type", sa.String()),
        sa.column("in_app_enabled", sa.Boolean()), sa.column("push_enabled", sa.Boolean()),
    )
    users = sa.table("users", sa.column("id", sa.Integer()))
    for kind in ("item_quantity_changed", "item_updated", "inventory_updated"):
        bind.execute(preferences.insert().from_select(
            ["user_id", "event_type", "in_app_enabled", "push_enabled"],
            sa.select(users.c.id, sa.literal(kind), sa.literal(False),
                      sa.literal(False)),
        ))


def downgrade() -> None:
    # A semantic reset cannot reconstruct old personal choices, rules or messages.
    raise RuntimeError("Personal notification redesign is irreversible; restore a pre-migration backup")
