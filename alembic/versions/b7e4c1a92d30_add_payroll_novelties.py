"""add payroll novelties

Revision ID: b7e4c1a92d30
Revises: 8f3c2a91d4b7
Create Date: 2026-10-26 19:10:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e4c1a92d30"
down_revision: str | None = "8f3c2a91d4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payroll_novelties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=6), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(period) = 6 "
            "AND CAST(period AS INTEGER) BETWEEN 190001 AND 299912 "
            "AND substr(period, 5, 2) BETWEEN '01' AND '12'",
            name=op.f("ck_payroll_novelties_valid_period"),
        ),
        sa.CheckConstraint(
            "kind IN ('REMUNERATIVE', 'NON_REMUNERATIVE', 'DEDUCTION', "
            "'CONTRIBUTION', 'AUXILIARY')",
            name=op.f("ck_payroll_novelties_valid_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_payroll_novelties_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_payroll_novelties_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payroll_novelties")),
        sa.UniqueConstraint(
            "employee_id",
            "period",
            "code",
            "source",
            name=op.f("uq_payroll_novelties_employee_period_code_source"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "external_id",
            name=op.f("uq_payroll_novelties_organization_external_id"),
        ),
    )
    op.create_index(
        "ix_payroll_novelty_employee_period",
        "payroll_novelties",
        ["employee_id", "period"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payroll_novelty_employee_period",
        table_name="payroll_novelties",
    )
    op.drop_table("payroll_novelties")
