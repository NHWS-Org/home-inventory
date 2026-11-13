"""Require Inbox for Push and remove the own-action preference."""

from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_notification_preferences_push_requires_inbox"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("notification_preferences")}
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("notification_preferences")}
    preferences = sa.table(
        "notification_preferences",
        sa.column("in_app_enabled", sa.Boolean()), sa.column("push_enabled", sa.Boolean()),
    )
    bind.execute(preferences.update().where(
        preferences.c.push_enabled.is_(True),
        preferences.c.in_app_enabled.is_(False),
    ).values(in_app_enabled=True))
    if "include_own_actions" in columns or CONSTRAINT not in constraints:
        with op.batch_alter_table("notification_preferences") as batch:
            if "include_own_actions" in columns:
                batch.drop_column("include_own_actions")
            if CONSTRAINT not in constraints:
                batch.create_check_constraint(CONSTRAINT, "NOT push_enabled OR in_app_enabled")


def downgrade() -> None:
    with op.batch_alter_table("notification_preferences") as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.add_column(sa.Column(
            "include_own_actions", sa.Boolean(), nullable=False, server_default="0",
        ))
