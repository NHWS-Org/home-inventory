"""add item_versions and inventory_versions shadow tables

Revision ID: b1c2d3e4f5a6
Revises: 4ef54a6a9ff5
Create Date: 2026-03-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = '4ef54a6a9ff5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'item_versions' not in existing_tables:
        op.create_table(
            'item_versions',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('item_id', sa.Integer(), nullable=False),
            sa.Column('inventory_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('quantity', sa.Integer(), nullable=True),
            sa.Column('version_num', sa.Integer(), nullable=False),
            sa.Column('operation', sa.String(length=16), nullable=False),
            sa.Column('changed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('changed_by_id', sa.Integer(),
                      sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('changed_by_username', sa.String(255), nullable=True),
            sa.Column('diff', sa.Text(), nullable=True),
        )

    if 'inventory_versions' not in existing_tables:
        op.create_table(
            'inventory_versions',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('inventory_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('type', sa.String(16), nullable=False),
            sa.Column('owner_id', sa.Integer(), nullable=True),
            sa.Column('owner_username', sa.String(255), nullable=True),
            sa.Column('version_num', sa.Integer(), nullable=False),
            sa.Column('operation', sa.String(length=16), nullable=False),
            sa.Column('changed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('changed_by_id', sa.Integer(),
                      sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('changed_by_username', sa.String(255), nullable=True),
            sa.Column('diff', sa.Text(), nullable=True),
        )

    for table_name, index_name, columns in (
        ("item_versions", "ix_item_versions_item_id", ["item_id"]),
        ("item_versions", "ix_item_versions_inventory_id", ["inventory_id"]),
        ("inventory_versions", "ix_inventory_versions_inventory_id", ["inventory_id"]),
    ):
        existing_indexes = {
            index["name"] for index in sa.inspect(bind).get_indexes(table_name)
        }
        if index_name not in existing_indexes:
            op.create_index(index_name, table_name, columns)

    # Backfill: crea la versione iniziale (v1, CREATE) per i record esistenti
    op.execute(
        """
        INSERT INTO inventory_versions (
            inventory_id, name, type, owner_id, owner_username,
            version_num, operation, changed_at, changed_by_id, changed_by_username, diff
        )
        SELECT
            i.id,
            i.name,
            i.type,
            i.owner_id,
            u_owner.username,
            1,
            'CREATE',
            COALESCE(i.data_ins, CURRENT_TIMESTAMP),
            i.user_ins,
            u_ins.username,
            NULL
        FROM inventories i
        LEFT JOIN users u_owner ON u_owner.id = i.owner_id
        LEFT JOIN users u_ins ON u_ins.id = i.user_ins
        WHERE NOT EXISTS (
            SELECT 1
            FROM inventory_versions iv
            WHERE iv.inventory_id = i.id
        )
        """
    )

    op.execute(
        """
        INSERT INTO item_versions (
            item_id, inventory_id, name, description, quantity,
            version_num, operation, changed_at, changed_by_id, changed_by_username, diff
        )
        SELECT
            it.id,
            it.inventory_id,
            it.name,
            it.description,
            it.quantity,
            1,
            'CREATE',
            COALESCE(it.data_ins, CURRENT_TIMESTAMP),
            it.user_ins,
            u_ins.username,
            NULL
        FROM items it
        LEFT JOIN users u_ins ON u_ins.id = it.user_ins
        WHERE NOT EXISTS (
            SELECT 1
            FROM item_versions iv
            WHERE iv.item_id = it.id
        )
        """
    )


def downgrade() -> None:
    op.drop_index('ix_item_versions_item_id', table_name='item_versions')
    op.drop_index('ix_item_versions_inventory_id', table_name='item_versions')
    op.drop_table('item_versions')
    op.drop_index('ix_inventory_versions_inventory_id', table_name='inventory_versions')
    op.drop_table('inventory_versions')
