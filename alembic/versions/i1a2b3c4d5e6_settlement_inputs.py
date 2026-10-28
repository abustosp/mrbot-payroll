"""Persist employee inputs for special settlements.

Revision ID: i1a2b3c4d5e6
Revises: h9a1b2c3d4e5
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i1a2b3c4d5e6"
down_revision: str | None = "h9a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payroll_settlement_inputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.UniqueConstraint("payroll_run_id", "employee_id"),
    )


def downgrade() -> None:
    op.drop_table("payroll_settlement_inputs")
