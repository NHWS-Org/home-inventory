"""Generic filters keep existing template IDs; scheduled triggers are opt-in."""

from alembic import op
import sqlalchemy as sa
from uuid import uuid4
import re

revision = "ba1c2d3e4f5a"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def audit_columns():
    return [
        sa.Column("data_ins", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("data_mod", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("user_ins", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("user_mod", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    ]


def _normalized_check(expression):
    tokens = re.findall(r"'(?:''|[^'])*'|[^']+", str(expression))
    return "".join(
        token if token.startswith("'") else "".join(token.lower().split()).replace("`", "").replace('"', "")
        for token in tokens
    )


def _native_check(table, expression):
    if op.get_bind().dialect.name == "sqlite":
        return _normalized_check(expression)
    # PostgreSQL rewrites IN to ANY/ARRAY and MySQL adds casts/charset markers.
    # Ask the same server to canonicalize the trusted expected expression.
    name = "_bootstrap_check_" + uuid4().hex[:20]
    op.create_check_constraint(name, table, str(expression))
    try:
        check = next(
            check for check in sa.inspect(op.get_bind()).get_check_constraints(table)
            if check["name"] == name
        )
        return _normalized_check(check["sqltext"])
    finally:
        op.drop_constraint(name, table, type_="check")


def _create_or_verify_table(name, *definitions):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if name not in inspector.get_table_names():
        op.create_table(name, *definitions)
        return

    expected = sa.Table(name, sa.MetaData(), *definitions)
    columns = {column["name"]: column for column in inspector.get_columns(name)}
    if set(columns) != set(expected.columns.keys()):
        raise RuntimeError(f"Bootstrap schema mismatch: {name} columns")
    for column in expected.columns:
        actual = columns[column.name]
        expected_type = column.type._type_affinity
        actual_type = actual["type"]._type_affinity
        mysql_boolean = (
            bind.dialect.name in {"mysql", "mariadb"}
            and isinstance(column.type, sa.Boolean)
            and actual["type"].__class__.__name__ == "TINYINT"
            and getattr(actual["type"], "display_width", None) in (None, 1)
        )
        mysql_json = (
            bind.dialect.name in {"mysql", "mariadb"}
            and isinstance(column.type, sa.JSON)
            and isinstance(actual["type"], sa.Text)
            and any(
                _normalized_check(check["sqltext"]) in {
                    f"json_valid({column.name})", f"(json_valid({column.name}))",
                }
                for check in inspector.get_check_constraints(name)
            )
        )
        if expected_type is not actual_type and not (mysql_boolean or mysql_json):
            raise RuntimeError(f"Bootstrap schema mismatch: {name}.{column.name} type")
        if isinstance(column.type, sa.String) and column.type.length != getattr(actual["type"], "length", None):
            raise RuntimeError(f"Bootstrap schema mismatch: {name}.{column.name} length")
        if actual["nullable"] != column.nullable:
            raise RuntimeError(f"Bootstrap schema mismatch: {name}.{column.name} nullability")
    if inspector.get_pk_constraint(name)["constrained_columns"] != [column.name for column in expected.primary_key.columns]:
        raise RuntimeError(f"Bootstrap schema mismatch: {name} primary key")

    unique = {constraint["name"]: constraint["column_names"] for constraint in inspector.get_unique_constraints(name)}
    checks = {constraint["name"]: _normalized_check(constraint["sqltext"]) for constraint in inspector.get_check_constraints(name)}
    foreign_keys = inspector.get_foreign_keys(name)
    for constraint in expected.constraints:
        if isinstance(constraint, sa.UniqueConstraint):
            if unique.get(constraint.name) != [column.name for column in constraint.columns]:
                raise RuntimeError(f"Bootstrap schema mismatch: {name} unique constraint {constraint.name}")
        elif isinstance(constraint, sa.CheckConstraint):
            if constraint.name not in checks or checks[constraint.name] != _native_check(name, constraint.sqltext):
                raise RuntimeError(f"Bootstrap schema mismatch: {name} check constraint {constraint.name}")
        elif isinstance(constraint, sa.ForeignKeyConstraint):
            target_table = constraint.elements[0].target_fullname.rsplit(".", 1)[0]
            target_columns = [element.target_fullname.rsplit(".", 1)[1] for element in constraint.elements]
            if not any(
                actual["constrained_columns"] == [column.name for column in constraint.columns]
                and actual["referred_table"] == target_table
                and actual["referred_columns"] == target_columns
                and (actual.get("options", {}).get("ondelete") or "NO ACTION").upper() == (constraint.ondelete or "NO ACTION").upper()
                for actual in foreign_keys
            ):
                raise RuntimeError(f"Bootstrap schema mismatch: {name} foreign key")


def _ensure_index(name, table, columns):
    indexes = {index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in indexes:
        op.create_index(name, table, columns)
    elif indexes[name]["column_names"] != columns or indexes[name].get("unique"):
        raise RuntimeError(f"Bootstrap schema mismatch: {table} index {name}")


def upgrade() -> None:
    with op.batch_alter_table("notification_preferences") as batch:
        batch.drop_constraint("ck_notification_preferences_event_type", type_="check")
        batch.create_check_constraint(
            "ck_notification_preferences_event_type",
            "event_type IN ('item_quantity_changed', 'item_updated', 'inventory_updated', 'filter_trigger_matched')",
        )
    _create_or_verify_table(
        "scheduled_triggers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("filter_id", sa.Integer(), sa.ForeignKey("filter_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("time", sa.String(5), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=False),
        sa.Column("inventory_ids", sa.JSON(), nullable=True),
        sa.Column("notify_mode", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("baseline", sa.JSON(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_result_count", sa.Integer(), nullable=True),
        sa.Column("last_container_count", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(64), nullable=True),
        *audit_columns(),
        sa.UniqueConstraint("user_ins", "name", name="uq_scheduled_triggers_owner_name"),
        sa.CheckConstraint("notify_mode IN ('always', 'changed')", name="ck_scheduled_triggers_mode"),
        sa.CheckConstraint("revision >= 1", name="ck_scheduled_triggers_revision"),
        sa.CheckConstraint(
            "(last_result_count IS NULL OR last_result_count >= 0) AND "
            "(last_container_count IS NULL OR last_container_count >= 0)",
            name="ck_scheduled_triggers_counts",
        ),
    )
    _ensure_index("ix_scheduled_triggers_enabled", "scheduled_triggers", ["enabled", "id"])
    _create_or_verify_table(
        "trigger_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trigger_id", sa.Integer(), sa.ForeignKey("scheduled_triggers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        *audit_columns(),
        sa.UniqueConstraint("trigger_id", "user_id", name="uq_trigger_subscriptions_user"),
    )
    _create_or_verify_table(
        "trigger_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trigger_id", sa.Integer(), sa.ForeignKey("scheduled_triggers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("logical_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("container_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(64), nullable=True),
        sa.UniqueConstraint("trigger_id", "scheduled_at", name="uq_trigger_runs_instant"),
        sa.UniqueConstraint("trigger_id", "logical_date", name="uq_trigger_runs_day"),
        sa.CheckConstraint("status IN ('completed', 'failed')", name="ck_trigger_runs_status"),
        sa.CheckConstraint(
            "(result_count IS NULL OR result_count >= 0) AND (container_count IS NULL OR container_count >= 0)",
            name="ck_trigger_runs_counts",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    events = sa.table("notification_events", sa.column("id", sa.Integer()), sa.column("payload", sa.JSON()))
    ids = sa.select(events.c.id).where(events.c.payload["event_type"].as_string() == "filter_trigger_matched")
    for name in ("push_deliveries", "notifications"):
        table = sa.table(name, sa.column("event_id", sa.Integer()))
        bind.execute(table.delete().where(table.c.event_id.in_(ids)))
    bind.execute(events.delete().where(events.c.payload["event_type"].as_string() == "filter_trigger_matched"))
    bind.execute(sa.text("DELETE FROM notification_preferences WHERE event_type = 'filter_trigger_matched'"))
    op.drop_table("trigger_runs")
    op.drop_table("trigger_subscriptions")
    op.drop_table("scheduled_triggers")
    with op.batch_alter_table("notification_preferences") as batch:
        batch.drop_constraint("ck_notification_preferences_event_type", type_="check")
        batch.create_check_constraint(
            "ck_notification_preferences_event_type",
            "event_type IN ('item_quantity_changed', 'item_updated', 'inventory_updated')",
        )
