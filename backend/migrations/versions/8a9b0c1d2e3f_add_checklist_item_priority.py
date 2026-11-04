"""add priority to items and item versions

Revision ID: 8a9b0c1d2e3f
Revises: f7a8b9c0d1e2
Create Date: 2026-11-03 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8a9b0c1d2e3f"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in ("items", "item_versions"):
        if table_name in inspector.get_table_names() and "priority" not in {
            column["name"] for column in inspector.get_columns(table_name)
        }:
            op.add_column(
                table_name,
                sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in ("item_versions", "items"):
        if table_name in inspector.get_table_names() and "priority" in {
            column["name"] for column in inspector.get_columns(table_name)
        }:
            op.drop_column(table_name, "priority")
