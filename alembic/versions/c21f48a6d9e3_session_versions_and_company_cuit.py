"""track session versions and scope company CUITs by organization

Revision ID: c21f48a6d9e3
Revises: b7e4c1a92d30
Create Date: 2026-10-26
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c21f48a6d9e3"
down_revision: str | None = "b7e4c1a92d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("session_version", sa.Integer(), server_default="1", nullable=False)
        )

    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_constraint("uq_companies_cuit", type_="unique")
        batch_op.create_unique_constraint(
            "uq_companies_organization_id_cuit", ["organization_id", "cuit"]
        )


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_constraint("uq_companies_organization_id_cuit", type_="unique")
        batch_op.create_unique_constraint("uq_companies_cuit", ["cuit"])

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("session_version")
