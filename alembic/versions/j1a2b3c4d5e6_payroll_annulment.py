"""Preserve annulled payrolls and link complete internal replacements."""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j1a2b3c4d5e6"
down_revision: str | None = "i1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payroll_runs") as batch:
        batch.drop_constraint(op.f("ck_payroll_runs_valid_status"), type_="check")
        batch.create_check_constraint("valid_status", "status IN ('DRAFT', 'VALIDATING', 'CALCULATED', 'IN_REVIEW', 'APPROVED', 'CLOSED', 'ERROR', 'ANNULLED')")
        batch.add_column(sa.Column("adjusts_run_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("adjustment_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("annulled_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("annulled_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("annulled_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_payroll_runs_adjusts_run_id_payroll_runs", "payroll_runs", ["adjusts_run_id"], ["id"])
        batch.create_foreign_key("fk_payroll_runs_annulled_by_users", "users", ["annulled_by"], ["id"])
        batch.create_unique_constraint("uq_payroll_runs_adjusts_run_id", ["adjusts_run_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM payroll_runs WHERE status = 'ANNULLED' OR adjusts_run_id IS NOT NULL LIMIT 1")).first():
        raise ValueError("No se puede revertir con liquidaciones anuladas o reemplazos existentes.")
    with op.batch_alter_table("payroll_runs") as batch:
        batch.drop_constraint("uq_payroll_runs_adjusts_run_id", type_="unique")
        batch.drop_constraint("fk_payroll_runs_adjusts_run_id_payroll_runs", type_="foreignkey")
        batch.drop_constraint("fk_payroll_runs_annulled_by_users", type_="foreignkey")
        for column in ("adjusts_run_id", "adjustment_reason", "annulled_reason", "annulled_by", "annulled_at"):
            batch.drop_column(column)
        batch.drop_constraint(op.f("ck_payroll_runs_valid_status"), type_="check")
        batch.create_check_constraint("valid_status", "status IN ('DRAFT', 'VALIDATING', 'CALCULATED', 'IN_REVIEW', 'APPROVED', 'CLOSED', 'ERROR')")
