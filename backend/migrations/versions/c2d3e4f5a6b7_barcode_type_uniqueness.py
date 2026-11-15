"""Enforce barcode uniqueness independently for inventories and lists."""

from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "ba1c2d3e4f5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(sa.text("""
        SELECT b.code, i.type, COUNT(*) AS n
        FROM item_barcodes b
        JOIN items t ON t.id = b.item_id
        JOIN inventories i ON i.id = t.inventory_id
        GROUP BY b.code, i.type HAVING COUNT(*) > 1
    """)).fetchall()
    if duplicates:
        raise RuntimeError(
            "Barcode duplicati tra contenitori dello stesso tipo: "
            + ", ".join(f"{row[0]} ({row[1]}: {row[2]})" for row in duplicates)
            + ". Rimuovere i duplicati prima di aggiornare."
        )
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("item_barcodes")}
    if "container_type" not in columns:
        with op.batch_alter_table("item_barcodes") as batch:
            batch.add_column(sa.Column("container_type", sa.String(16), nullable=True))
    bind.execute(sa.text("""
        UPDATE item_barcodes SET container_type = (
            SELECT inventories.type FROM items
            JOIN inventories ON inventories.id = items.inventory_id
            WHERE items.id = item_barcodes.item_id
        )
    """))
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("item_barcodes")}
    unique_names = {constraint["name"] for constraint in inspector.get_unique_constraints("item_barcodes")}
    check_names = {constraint["name"] for constraint in inspector.get_check_constraints("item_barcodes")}
    with op.batch_alter_table("item_barcodes") as batch:
        if columns["container_type"]["nullable"]:
            batch.alter_column("container_type", existing_type=sa.String(16), nullable=False)
        if "uq_item_barcodes_type_code" not in unique_names:
            batch.create_unique_constraint("uq_item_barcodes_type_code", ["container_type", "code"])
        if "ck_item_barcodes_container_type" not in check_names:
            batch.create_check_constraint(
                "ck_item_barcodes_container_type", "container_type IN ('INVENTORY', 'CHECKLIST')"
            )


def downgrade() -> None:
    with op.batch_alter_table("item_barcodes") as batch:
        batch.drop_constraint("ck_item_barcodes_container_type", type_="check")
        batch.drop_constraint("uq_item_barcodes_type_code", type_="unique")
        batch.drop_column("container_type")
