"""Isolate organization parameters while retaining the global catalog."""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k1a2b3c4d5e6"
down_revision: str | None = "j1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("normative_parameters") as batch:
        batch.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_normative_parameters_organization_id_organizations", "organizations", ["organization_id"], ["id"])
        batch.drop_constraint("uq_normative_parameters_jurisdiction", type_="unique")
    fields = ["jurisdiction", "code", "agreement_code", "category_code", "valid_from", "version"]
    op.create_index("uq_parameter_global", "normative_parameters", fields, unique=True, sqlite_where=sa.text("organization_id IS NULL"), postgresql_where=sa.text("organization_id IS NULL"))
    op.create_index("uq_parameter_organization", "normative_parameters", ["organization_id", *fields], unique=True, sqlite_where=sa.text("organization_id IS NOT NULL"), postgresql_where=sa.text("organization_id IS NOT NULL"))


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM normative_parameters WHERE organization_id IS NOT NULL LIMIT 1")).first():
        raise ValueError("Elimine o consolide los parámetros de organizaciones antes de revertir.")
    op.drop_index("uq_parameter_organization", table_name="normative_parameters")
    op.drop_index("uq_parameter_global", table_name="normative_parameters")
    with op.batch_alter_table("normative_parameters") as batch:
        batch.drop_constraint("fk_normative_parameters_organization_id_organizations", type_="foreignkey")
        batch.drop_column("organization_id")
        batch.create_unique_constraint("uq_normative_parameters_jurisdiction", ["jurisdiction", "code", "agreement_code", "category_code", "valid_from", "version"])
