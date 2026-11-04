"""backfill initial shadow versions for existing rows

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-03-13 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotente: inserisce CREATE v1 solo se non esiste gia una versione per l'entita.
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
    # Non rimuoviamo dati di audit in downgrade per evitare perdita storica.
    pass
