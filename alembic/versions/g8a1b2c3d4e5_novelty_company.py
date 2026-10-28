"""Scope payroll novelties to a company.

Revision ID: g8a1b2c3d4e5
Revises: f7a1b2c3d4e5
"""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa

from alembic import op

revision: str = "g8a1b2c3d4e5"
down_revision: str | None = "f7a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payroll_novelties") as batch:
        batch.add_column(sa.Column("company_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_payroll_novelties_company_id_companies", "companies", ["company_id"], ["id"]
        )
        batch.drop_constraint("uq_payroll_novelties_employee_period_code_source", type_="unique")
        batch.create_unique_constraint(
            "uq_payroll_novelties_employee_company_period_code_source",
            ["employee_id", "company_id", "period", "code", "source"],
        )

    bind = op.get_bind()
    novelties = sa.table(
        "payroll_novelties",
        sa.column("id"),
        sa.column("employee_id"),
        sa.column("period"),
        sa.column("company_id"),
    )
    contracts = sa.table(
        "employment_contracts",
        sa.column("employee_id"),
        sa.column("company_id"),
        sa.column("valid_from", sa.Date()),
        sa.column("valid_to", sa.Date()),
    )
    companies = sa.table("companies", sa.column("id"), sa.column("organization_id"))
    employees = sa.table("employees", sa.column("id"), sa.column("organization_id"))
    for novelty in bind.execute(
        sa.select(novelties.c.id, novelties.c.employee_id, novelties.c.period)
    ):
        year, month = int(novelty.period[:4]), int(novelty.period[4:])
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
        matches = (
            bind.execute(
                sa.select(contracts.c.company_id)
                .distinct()
                .select_from(
                    contracts.join(companies, companies.c.id == contracts.c.company_id).join(
                        employees, employees.c.id == contracts.c.employee_id
                    )
                )
                .where(
                    contracts.c.employee_id == novelty.employee_id,
                    companies.c.organization_id == employees.c.organization_id,
                    contracts.c.valid_from < end,
                    sa.or_(contracts.c.valid_to.is_(None), contracts.c.valid_to >= start),
                )
            )
            .scalars()
            .all()
        )
        if len(matches) == 1:
            bind.execute(
                novelties.update().where(novelties.c.id == novelty.id).values(company_id=matches[0])
            )


def downgrade() -> None:
    # The old constraint deliberately rejects downgrade if companies now have
    # conflicting novelties, instead of discarding data.
    with op.batch_alter_table("payroll_novelties") as batch:
        batch.drop_constraint(
            "uq_payroll_novelties_employee_company_period_code_source", type_="unique"
        )
        batch.create_unique_constraint(
            "uq_payroll_novelties_employee_period_code_source",
            ["employee_id", "period", "code", "source"],
        )
        batch.drop_constraint("fk_payroll_novelties_company_id_companies", type_="foreignkey")
        batch.drop_column("company_id")
