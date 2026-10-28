"""Scope effective parameters by agreement and category.

Revision ID: h9a1b2c3d4e5
Revises: g8a1b2c3d4e5
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h9a1b2c3d4e5"
down_revision: str | None = "g8a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("normative_parameters") as batch:
        batch.add_column(sa.Column("agreement_code", sa.String(40), nullable=False, server_default=""))
        batch.add_column(sa.Column("category_code", sa.String(40), nullable=False, server_default=""))
        batch.drop_constraint("uq_normative_parameters_jurisdiction", type_="unique")
        batch.create_unique_constraint("uq_normative_parameters_jurisdiction", [
            "jurisdiction", "code", "agreement_code", "category_code", "valid_from", "version",
        ])
        batch.create_check_constraint("parameter_category_scope", "category_code = '' OR agreement_code <> ''")


def downgrade() -> None:
    # A populated scoped catalog must be consolidated explicitly, never discarded.
    connection = op.get_bind()
    duplicates = connection.execute(sa.text(
        "SELECT 1 FROM normative_parameters GROUP BY jurisdiction, code, valid_from, version "
        "HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicates:
        raise ValueError("Consolidar parámetros por convenio antes de revertir la migración.")
    with op.batch_alter_table("normative_parameters") as batch:
        batch.drop_constraint("uq_normative_parameters_jurisdiction", type_="unique")
        batch.drop_constraint(op.f("ck_normative_parameters_parameter_category_scope"), type_="check")
        batch.drop_column("category_code")
        batch.drop_column("agreement_code")
        batch.create_unique_constraint("uq_normative_parameters_jurisdiction", [
            "jurisdiction", "code", "valid_from", "version",
        ])
