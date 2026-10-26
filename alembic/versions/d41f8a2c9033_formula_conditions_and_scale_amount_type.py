"""carry formula conditions/rounding and scale amount type (B-02, B-07)

Revision ID: d41f8a2c9033
Revises: c21f48a6d9e3
Create Date: 2026-10-26
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d41f8a2c9033"
down_revision: str | None = "c21f48a6d9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("formula_versions") as batch_op:
        batch_op.add_column(sa.Column("conditions", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("depends_on", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("rounding", sa.JSON(), nullable=True))

    with op.batch_alter_table("salary_scales") as batch_op:
        batch_op.add_column(
            sa.Column("amount_type", sa.String(length=16), server_default="basico", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("salary_scales") as batch_op:
        batch_op.drop_column("amount_type")

    with op.batch_alter_table("formula_versions") as batch_op:
        batch_op.drop_column("rounding")
        batch_op.drop_column("depends_on")
        batch_op.drop_column("conditions")
