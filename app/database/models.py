from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utc_now


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="valid_role"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="viewer", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("organization_id", "cuit", name="uq_companies_organization_id_cuit"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    cuit: Mapped[str] = mapped_column(String(11), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(200))
    tax_activity: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Establishment(Base):
    __tablename__ = "establishments"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("organization_id", "employee_code", name="uq_employee_org_code"),
        UniqueConstraint("organization_id", "cuil", name="uq_employee_org_cuil"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    employee_code: Mapped[str] = mapped_column(String(40), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    cuil: Mapped[str | None] = mapped_column(String(11), index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    birth_date: Mapped[date | None] = mapped_column(Date)
    hire_date: Mapped[date | None] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    address: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EmploymentContract(Base):
    __tablename__ = "employment_contracts"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="inclusive_validity"),
        Index("ix_contract_employee_dates", "employee_id", "valid_from", "valid_to"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    agreement_id: Mapped[int | None] = mapped_column(ForeignKey("collective_agreements.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("agreement_categories.id"))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    employment_type: Mapped[str] = mapped_column(String(40), default="full_time", nullable=False)
    weekly_hours: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    monthly_salary: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EmploymentHistory(Base):
    __tablename__ = "employment_history"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="inclusive_validity"),
        Index("ix_employment_history_employee_dates", "employee_id", "valid_from", "valid_to"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("employment_contracts.id", ondelete="SET NULL"))
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)


class CollectiveAgreement(Base):
    __tablename__ = "collective_agreements"
    __table_args__ = (UniqueConstraint("code", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    activity: Mapped[str | None] = mapped_column(String(160))
    scope: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AgreementCategory(Base):
    __tablename__ = "agreement_categories"
    __table_args__ = (UniqueConstraint("agreement_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    agreement_id: Mapped[int] = mapped_column(ForeignKey("collective_agreements.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class SalaryScale(Base):
    __tablename__ = "salary_scales"
    __table_args__ = (
        UniqueConstraint("category_id", "valid_from"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="inclusive_validity"),
        Index("ix_salary_scale_validity", "category_id", "valid_from", "valid_to"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("agreement_categories.id", ondelete="CASCADE"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    additional: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    # B-02: "basico" (remunerative base) vs "conformado" (total split on load).
    amount_type: Mapped[str] = mapped_column(
        String(16), default="basico", server_default="basico", nullable=False
    )
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("normative_documents.id"))


class PayrollConcept(Base):
    """Un concepto es inmutable cuando tiene fórmulas o ítems (V2-24).

    La referencia concepto↔fórmula vive en JSON sin FK en DB; el único
    guard es el 409 de ``DELETE /concepts`` (solo fórmulas APPROVED).
    No borrar por ORM/SQL directo: la corrida cae al canal de error por
    empleado en vez de fallar al borrar. Ver test pin V2-24.
    """

    __tablename__ = "payroll_concepts"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        CheckConstraint("nature IN ('REMUNERATIVE', 'NON_REMUNERATIVE', 'DEDUCTION', 'CONTRIBUTION', 'AUXILIARY')", name="valid_nature"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    nature: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ConceptTaxTreatment(Base):
    __tablename__ = "concept_tax_treatments"
    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("payroll_concepts.id", ondelete="CASCADE"), unique=True, nullable=False)
    subject_to_social_security: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subject_to_health_insurance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subject_to_income_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tax_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class FormulaDefinition(Base):
    __tablename__ = "formula_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    # B-26: optional agreement scope (CCT code + category code, NULL = all).
    agreement_code: Mapped[str | None] = mapped_column(String(40))
    category_code: Mapped[str | None] = mapped_column(String(40))
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class FormulaVersion(Base):
    __tablename__ = "formula_versions"
    __table_args__ = (
        UniqueConstraint("formula_id", "version"),
        CheckConstraint("status IN ('DRAFT', 'VALIDATED', 'APPROVED', 'OBSOLETE')", name="valid_status"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="inclusive_validity"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    formula_id: Mapped[int] = mapped_column(ForeignKey("formula_definitions.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    expression: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # B-07: conditions/rounding/depends_on travel with the version so the
    # service executes exactly what was approved.
    conditions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    depends_on: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    rounding: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, default=date.min, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiProposal(Base):
    """Persisted, human-supervised AI proposal.

    A proposal is *not* a payroll rule. Publication is a separate, explicit
    operation that always creates a ``DRAFT`` formula version.
    """

    __tablename__ = "ai_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'validated', 'approved', 'rejected', 'published')",
            name="valid_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(200), nullable=False)
    document_hash: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(500))
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_formula_id: Mapped[int | None] = mapped_column(ForeignKey("formula_definitions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


# Backwards/forwards compatible naming for imports in application code.
AIProposal = AiProposal


class NormativeDocument(Base):
    __tablename__ = "normative_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    document_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    file_path: Mapped[str | None] = mapped_column(String(1000))
    checksum: Mapped[str | None] = mapped_column(String(128), unique=True)
    published_at: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class NormativeParameter(Base):
    __tablename__ = "normative_parameters"
    __table_args__ = (
        UniqueConstraint("jurisdiction", "code", "valid_from", "version"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="inclusive_validity"),
        Index("ix_parameter_lookup", "jurisdiction", "code", "valid_from", "valid_to"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    jurisdiction: Mapped[str] = mapped_column(String(80), default="AR", nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("normative_documents.id"))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Ruleset(Base):
    __tablename__ = "ruleset_versions"
    __table_args__ = (
        UniqueConstraint("code", "version"),
        CheckConstraint("status IN ('DRAFT', 'APPROVED', 'OBSOLETE')", name="valid_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        CheckConstraint("status IN ('DRAFT', 'VALIDATING', 'CALCULATED', 'IN_REVIEW', 'APPROVED', 'CLOSED', 'ERROR')", name="valid_status"),
        CheckConstraint("period_end >= period_start", name="valid_period"),
        Index("ix_payroll_run_company_period", "company_id", "period_start", "period_end"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    run_type: Mapped[str] = mapped_column(String(40), default="MONTHLY", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    ruleset_id: Mapped[int | None] = mapped_column(ForeignKey("ruleset_versions.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    inputs_hash: Mapped[str | None] = mapped_column(String(128))
    results_hash: Mapped[str | None] = mapped_column(String(128))


class PayrollResult(Base):
    __tablename__ = "payroll_results"
    __table_args__ = (
        UniqueConstraint("payroll_run_id", "employee_id"),
        CheckConstraint("remunerative >= 0 AND non_remunerative >= 0 AND deductions >= 0 AND contributions >= 0 AND gross >= 0 AND net >= 0 AND employer_cost >= 0", name="nonnegative_totals"),
        Index("ix_payroll_results_employee_id", "employee_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    remunerative: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    non_remunerative: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    deductions: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    contributions: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    gross: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    net: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    employer_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results_hash: Mapped[str | None] = mapped_column(String(128))


class PayrollItem(Base):
    __tablename__ = "payroll_items"
    __table_args__ = (
        Index("ix_payroll_items_result_id", "payroll_result_id"),
        Index("ix_payroll_items_concept_id", "concept_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_result_id: Mapped[int] = mapped_column(ForeignKey("payroll_results.id", ondelete="CASCADE"), nullable=False)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_concepts.id"))
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(160), nullable=False)
    nature: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)


class PayrollNovelty(Base):
    """A novelty imputed to one employee for a payroll period.

    ``period`` is the imputation period in ``AAAAMM`` format. ``kind`` classifies
    the novelty nature using the same values as ``PayrollConcept.nature``. The
    natural key ``(employee_id, period, code, source)`` makes imports
    idempotent, while ``(organization_id, external_id)`` prevents the same
    external record from being imported twice. Multiple null ``external_id``
    values are allowed by the unique constraint, as required for manually
    created rows.
    """

    __tablename__ = "payroll_novelties"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "period",
            "code",
            "source",
            name="uq_payroll_novelties_employee_period_code_source",
        ),
        UniqueConstraint(
            "organization_id",
            "external_id",
            name="uq_payroll_novelties_organization_external_id",
        ),
        CheckConstraint(
            "length(period) = 6 "
            "AND CAST(period AS INTEGER) BETWEEN 190001 AND 299912 "
            "AND substr(period, 5, 2) BETWEEN '01' AND '12'",
            name="valid_period",
        ),
        CheckConstraint(
            "kind IN ('REMUNERATIVE', 'NON_REMUNERATIVE', 'DEDUCTION', "
            "'CONTRIBUTION', 'AUXILIARY')",
            name="valid_kind",
        ),
        Index("ix_payroll_novelty_employee_period", "employee_id", "period"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(6), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(24), default="REMUNERATIVE", nullable=False
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(20))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="import", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PayrollTrace(Base):
    __tablename__ = "payroll_calculation_traces"
    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_result_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_results.id", ondelete="CASCADE"))
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    event: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PayrollApproval(Base):
    __tablename__ = "payroll_approvals"
    __table_args__ = (UniqueConstraint("payroll_run_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_organization_id", "organization_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (Index("ix_background_jobs_status_created", "status", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
