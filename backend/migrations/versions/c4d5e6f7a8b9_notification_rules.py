"""Add explicitly configured notification rules.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
"""

from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "notification_rules" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_id", sa.Integer(),
                  sa.ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("threshold", sa.Integer()),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("data_ins", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("data_mod", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("user_ins", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("user_mod", sa.Integer(), sa.ForeignKey("users.id")),
        sa.CheckConstraint(
            "event_type IN ('inventory_shared', 'item_quantity_changed', 'checklist_completed')",
            name="ck_notification_rules_event_type",
        ),
        sa.CheckConstraint(
            "(event_type = 'item_quantity_changed' AND threshold IS NOT NULL AND threshold >= 0)"
            " OR (event_type != 'item_quantity_changed' AND threshold IS NULL)",
            name="ck_notification_rules_threshold",
        ),
    )
    op.create_index("ix_notification_rules_inventory_id", "notification_rules", ["inventory_id"])


def downgrade() -> None:
    op.drop_table("notification_rules")
