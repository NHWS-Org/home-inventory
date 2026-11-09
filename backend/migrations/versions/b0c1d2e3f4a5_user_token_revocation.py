"""Support per-user revocation of tokens after password recovery."""

from alembic import op
import sqlalchemy as sa

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "auth_revoked_before" not in columns:
        op.add_column("users", sa.Column("auth_revoked_before", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("auth_revoked_before")
