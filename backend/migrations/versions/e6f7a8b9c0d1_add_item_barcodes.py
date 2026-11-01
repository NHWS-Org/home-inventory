"""add item_barcodes and barcode_product_cache

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-10-12 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())

    if 'item_barcodes' not in existing_tables:
        op.create_table(
            'item_barcodes',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('item_id', sa.Integer(), sa.ForeignKey('items.id', ondelete='CASCADE'), nullable=False),
            sa.Column('code', sa.String(), nullable=False),
            sa.Column('format', sa.String(), nullable=True),
            sa.Column('data_ins', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('data_mod', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('user_ins', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('user_mod', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.UniqueConstraint('item_id', 'code', name='uq_item_barcodes_item_code'),
        )
        op.create_index('ix_item_barcodes_id', 'item_barcodes', ['id'])
        op.create_index('ix_item_barcodes_item_id', 'item_barcodes', ['item_id'])
        op.create_index('ix_item_barcodes_code', 'item_barcodes', ['code'])

    if 'barcode_product_cache' not in existing_tables:
        op.create_table(
            'barcode_product_cache',
            sa.Column('code', sa.String(), primary_key=True),
            sa.Column('found', sa.Boolean(), nullable=False),
            sa.Column('name', sa.String(), nullable=True),
            sa.Column('brand', sa.String(), nullable=True),
            sa.Column('quantity_label', sa.String(), nullable=True),
            sa.Column('image_url', sa.String(), nullable=True),
            sa.Column('source', sa.String(), nullable=True),
            sa.Column('fetched_at', sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS barcode_product_cache")
    op.execute("DROP TABLE IF EXISTS item_barcodes")
