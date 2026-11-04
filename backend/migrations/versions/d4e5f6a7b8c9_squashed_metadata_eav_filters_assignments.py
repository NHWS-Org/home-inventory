"""squashed: add metadata EAV, filter templates, definition scopes and assignments

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-01 10:00:00.000000

Squashes (in order):
  - d4e5f6a7b8c9  add_metadata_eav_tables
  - e5f6a7b8c9d0  add_filter_templates
  - f6a7b8c9d0e1  add_metadata_definition_scopes
  - a1b2c3d4e5f6  add_metadata_assignments_table
  - b2c3d4e5f6a7  make_filter_templates_global

Final state introduced by this migration:
  * metadata_definitions        – chiave globale unica, nessun riferimento a inventory/scope
  * item_metadata_values        – valori EAV per gli item
  * metadata_definition_assignments – collega una definizione a scope/inventory_type/inventory_id
  * filter_templates            – inventory_id nullable, nessuna FK su inventories
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    where: str | None = None,
) -> None:
    bind = op.get_bind()
    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes(table_name)
    }
    if index_name in existing_indexes:
        return

    dialect = bind.dialect.name
    if where and dialect not in {"postgresql", "sqlite"}:
        return
    index_options = {}
    if where:
        index_options[f"{dialect}_where"] = sa.text(where)
    if dialect in {"mysql", "mariadb"} and columns == ["value_text"]:
        index_options["mysql_length"] = {"value_text": 191}
    op.create_index(
        index_name,
        table_name,
        columns,
        unique=unique,
        **index_options,
    )


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    bind = op.get_bind()
    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes(table_name)
    }
    if index_name in existing_indexes:
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # -------------------------------------------------------------------------
    # 1. metadata_definitions
    #    Stato finale: nessuna colonna scope/inventory_type/inventory_id.
    #    Chiave univoca globale su `key`.
    # -------------------------------------------------------------------------
    if 'metadata_definitions' not in existing_tables:
        op.create_table(
            'metadata_definitions',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('key', sa.String(length=64), nullable=False),
            sa.Column('label', sa.String(length=128), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('field_type', sa.String(length=16), nullable=False),
            sa.Column('list_options', sa.JSON(), nullable=True),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_required', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('data_ins', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('data_mod', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('user_ins', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('user_mod', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.UniqueConstraint('key', name='uq_metadata_definitions_key'),
            sa.CheckConstraint(
                "field_type IN ('TEXT', 'NUMBER', 'BOOLEAN', 'DATE', 'LIST')",
                name='ck_metadata_definitions_field_type',
            ),
        )

    # -------------------------------------------------------------------------
    # 2. item_metadata_values
    # -------------------------------------------------------------------------
    if 'item_metadata_values' not in existing_tables:
        op.create_table(
            'item_metadata_values',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('item_id', sa.Integer(), sa.ForeignKey('items.id', ondelete='CASCADE'), nullable=False),
            sa.Column('definition_id', sa.Integer(), sa.ForeignKey('metadata_definitions.id', ondelete='CASCADE'), nullable=False),
            sa.Column('value_text', sa.Text(), nullable=True),
            sa.Column('value_number', sa.Numeric(14, 4), nullable=True),
            sa.Column('value_boolean', sa.Boolean(), nullable=True),
            sa.Column('value_date', sa.Date(), nullable=True),
            sa.Column('data_ins', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('data_mod', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('user_ins', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('user_mod', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.UniqueConstraint('item_id', 'definition_id', name='uq_item_metadata_values_item_definition'),
            sa.CheckConstraint(
                "("
                "CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END + "
                "CASE WHEN value_number IS NOT NULL THEN 1 ELSE 0 END + "
                "CASE WHEN value_boolean IS NOT NULL THEN 1 ELSE 0 END + "
                "CASE WHEN value_date IS NOT NULL THEN 1 ELSE 0 END"
                ") = 1",
                name='ck_item_metadata_values_single_typed_value',
            ),
        )

    for column_name in (
        "item_id",
        "definition_id",
        "value_text",
        "value_number",
        "value_boolean",
        "value_date",
    ):
        _create_index_if_missing(
            f"ix_item_metadata_values_{column_name}",
            "item_metadata_values",
            [column_name],
        )

    # -------------------------------------------------------------------------
    # 3. metadata_definition_assignments
    #    Collega ogni definizione a uno scope: GLOBAL / INVENTORY_TYPE / INVENTORY
    # -------------------------------------------------------------------------
    if 'metadata_definition_assignments' not in existing_tables:
        op.create_table(
            'metadata_definition_assignments',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('definition_id', sa.Integer(), sa.ForeignKey('metadata_definitions.id', ondelete='CASCADE'), nullable=False),
            sa.Column('scope', sa.String(32), nullable=False),
            sa.Column('inventory_type', sa.String(16), nullable=True),
            sa.Column('inventory_id', sa.Integer(), sa.ForeignKey('inventories.id', ondelete='CASCADE'), nullable=True),
            sa.Column('data_ins', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('data_mod', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('user_ins', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('user_mod', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.CheckConstraint(
                "scope IN ('GLOBAL', 'INVENTORY_TYPE', 'INVENTORY')",
                name='ck_mda_scope',
            ),
            sa.CheckConstraint(
                "inventory_type IS NULL OR inventory_type IN ('INVENTORY', 'CHECKLIST')",
                name='ck_mda_inventory_type',
            ),
            sa.CheckConstraint(
                "(scope = 'GLOBAL' AND inventory_id IS NULL AND inventory_type IS NULL) OR "
                "(scope = 'INVENTORY_TYPE' AND inventory_id IS NULL AND inventory_type IS NOT NULL) OR "
                "(scope = 'INVENTORY' AND inventory_id IS NOT NULL)",
                name='ck_mda_scope_target',
            ),
        )
    for index_name, column_name in (
        ("ix_mda_definition_id", "definition_id"),
        ("ix_mda_inventory_id", "inventory_id"),
        ("ix_mda_inventory_type", "inventory_type"),
        ("ix_mda_scope", "scope"),
    ):
        _create_index_if_missing(index_name, "metadata_definition_assignments", [column_name])
    _create_index_if_missing(
        "uq_mda_global_def",
        "metadata_definition_assignments",
        ["definition_id"],
        unique=True,
        where="scope = 'GLOBAL'",
    )
    _create_index_if_missing(
        "uq_mda_type_def",
        "metadata_definition_assignments",
        ["definition_id", "inventory_type"],
        unique=True,
        where="scope = 'INVENTORY_TYPE'",
    )
    _create_index_if_missing(
        "uq_mda_inventory_def",
        "metadata_definition_assignments",
        ["definition_id", "inventory_id"],
        unique=True,
        where="scope = 'INVENTORY'",
    )

    # -------------------------------------------------------------------------
    # 4. filter_templates
    #    Stato finale: inventory_id nullable, nessuna FK su inventories,
    #    nessun vincolo unico su (inventory_id, name).
    # -------------------------------------------------------------------------
    if 'filter_templates' not in existing_tables:
        op.create_table(
            'filter_templates',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('inventory_id', sa.Integer(), nullable=True),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('filter_type', sa.String(length=32), nullable=False),
            sa.Column('criteria', sa.JSON(), nullable=False),
            sa.Column('is_shared', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('data_ins', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('data_mod', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('user_ins', sa.Integer(), nullable=True),
            sa.Column('user_mod', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['user_ins'], ['users.id']),
            sa.ForeignKeyConstraint(['user_mod'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            op.f('ix_filter_templates_inventory_id'),
            'filter_templates',
            ['inventory_id'],
            unique=False,
        )
        op.create_index(
            op.f('ix_filter_templates_id'),
            'filter_templates',
            ['id'],
            unique=False,
        )


def downgrade() -> None:
    # filter_templates
    _drop_index_if_exists(op.f('ix_filter_templates_id'), 'filter_templates')
    _drop_index_if_exists(op.f('ix_filter_templates_inventory_id'), 'filter_templates')
    op.drop_table('filter_templates')

    # metadata_definition_assignments
    for index_name in (
        "uq_mda_inventory_def",
        "uq_mda_type_def",
        "uq_mda_global_def",
        "ix_mda_scope",
        "ix_mda_inventory_type",
        "ix_mda_inventory_id",
        "ix_mda_definition_id",
    ):
        _drop_index_if_exists(index_name, 'metadata_definition_assignments')
    op.drop_table('metadata_definition_assignments')

    # item_metadata_values
    for column_name in (
        "value_date",
        "value_boolean",
        "value_number",
        "value_text",
        "definition_id",
        "item_id",
    ):
        _drop_index_if_exists(
            f"ix_item_metadata_values_{column_name}",
            'item_metadata_values',
        )
    op.drop_table('item_metadata_values')

    # metadata_definitions
    op.drop_table('metadata_definitions')
