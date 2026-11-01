"""add list_assignments

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-10-12 17:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if 'list_assignments' in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        'list_assignments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('list_item_id', sa.Integer(), sa.ForeignKey('items.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('source_item_id', sa.Integer(), sa.ForeignKey('items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('applied_at', sa.DateTime(), nullable=True),
        sa.Column('applied_qty', sa.Integer(), nullable=True),
        sa.Column('data_ins', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('data_mod', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('user_ins', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('user_mod', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.CheckConstraint('qty >= 1', name='ck_list_assignments_qty_positive'),
    )
    op.create_index('ix_list_assignments_id', 'list_assignments', ['id'])
    op.create_index('ix_list_assignments_source_item_id', 'list_assignments', ['source_item_id'])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS list_assignments")
