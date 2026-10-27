"""hot FK indexes for deletes and payroll reads (V2-21)

Revision ID: f7a1b2c3d4e5
Revises: e5f1a2b3c4d5
Create Date: 2026-10-26
"""
from collections.abc import Sequence

from alembic import op

revision: str = "f7a1b2c3d4e5"
down_revision: str | None = "e5f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_payroll_results_employee_id", "payroll_results", ["employee_id"]
    )
    op.create_index(
        "ix_payroll_items_result_id", "payroll_items", ["payroll_result_id"]
    )
    op.create_index("ix_payroll_items_concept_id", "payroll_items", ["concept_id"])
    op.create_index(
        "ix_audit_logs_organization_id", "audit_logs", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_organization_id", table_name="audit_logs")
    op.drop_index("ix_payroll_items_concept_id", table_name="payroll_items")
    op.drop_index("ix_payroll_items_result_id", table_name="payroll_items")
    op.drop_index("ix_payroll_results_employee_id", table_name="payroll_results")
