"""formula agreement scope for per-CCT calculation (B-26)

Revision ID: e5f1a2b3c4d5
Revises: d41f8a2c9033
Create Date: 2026-10-26
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f1a2b3c4d5"
down_revision: str | None = "d41f8a2c9033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("formula_definitions") as batch_op:
        batch_op.add_column(sa.Column("agreement_code", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("category_code", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("formula_definitions") as batch_op:
        batch_op.drop_column("category_code")
        batch_op.drop_column("agreement_code")
