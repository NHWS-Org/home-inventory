"""Persist administrative security actions."""

from alembic import op
import sqlalchemy as sa

revision = "d6e7f8a9b0c1"
down_revision = "9b0c1d2e3f4a"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("security_audit"):
        op.create_table(
            "security_audit",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("actor_username", sa.String(255), nullable=False),
            sa.Column("action", sa.String(32), nullable=False),
            sa.Column("outcome", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_before", sa.BigInteger(), nullable=True),
            sa.Column("sessions_revoked", sa.Integer(), nullable=False),
        )
        op.create_index("ix_security_audit_created_at", "security_audit", ["created_at"])
        op.create_index("ix_security_audit_revoked_before", "security_audit", ["revoked_before"])


def downgrade():
    op.drop_table("security_audit")
