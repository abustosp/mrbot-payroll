from datetime import date, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginInput(BaseModel):
    email: str
    password: str


class UserRead(ORMModel):
    id: int
    organization_id: int
    email: str
    role: str


class CompanyInput(BaseModel):
    cuit: str = Field(min_length=11, max_length=11, pattern=r"^\d{11}$")
    legal_name: str = Field(min_length=1, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    tax_activity: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    active: bool = True


class CompanyRead(ORMModel):
    id: int
    organization_id: int
    cuit: str
    legal_name: str
    trade_name: str | None
    tax_activity: str | None
    address: str | None
    active: bool


class EmployeeInput(BaseModel):
    employee_code: str = Field(min_length=1, max_length=40)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    cuil: str | None = Field(default=None, min_length=11, max_length=11, pattern=r"^\d{11}$")
    email: str | None = Field(default=None, max_length=254)
    birth_date: date | None = None
    hire_date: date | None = None
    termination_date: date | None = None
    address: str | None = Field(default=None, max_length=300)
    active: bool = True


class EmployeeRead(ORMModel):
    id: int
    organization_id: int
    employee_code: str
    first_name: str
    last_name: str
    cuil: str | None
    email: str | None
    birth_date: date | None
    hire_date: date | None
    termination_date: date | None
    address: str | None
    active: bool


class AgreementInput(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    year: int = Field(ge=1900, le=9999)
    name: str = Field(min_length=1, max_length=200)
    activity: str | None = Field(default=None, max_length=160)
    scope: str | None = None
    active: bool = True


class AgreementRead(ORMModel):
    id: int
    code: str
    year: int
    name: str
    activity: str | None
    scope: str | None
    active: bool


class ConceptInput(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    nature: Literal["REMUNERATIVE", "NON_REMUNERATIVE", "DEDUCTION", "CONTRIBUTION", "AUXILIARY"]
    description: str | None = None
    active: bool = True


class ConceptRead(ORMModel):
    id: int
    organization_id: int
    code: str
    name: str
    nature: str
    description: str | None
    active: bool


class FormulaInput(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    formula: dict[str, Any]
    valid_from: date = Field(default_factory=date.today)
    valid_to: date | None = None

    @field_validator("code")
    @classmethod
    def code_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El código de fórmula no puede estar vacío")
        return value

    @field_validator("formula")
    @classmethod
    def formula_is_nonempty_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("La fórmula debe contener una expresión DSL")
        return value

    @field_validator("valid_to")
    @classmethod
    def validity_is_inclusive(cls, value: date | None, info):
        start = info.data.get("valid_from")
        if value is not None and start is not None and value < start:
            raise ValueError("valid_to debe ser igual o posterior a valid_from")
        return value


class FormulaVersionInput(BaseModel):
    """Payload for creating a new version of an existing formula.

    ``expression`` is accepted as an alias of ``formula`` because both names are
    used across the engine and the API documentation.
    """

    model_config = ConfigDict(populate_by_name=True)

    formula: dict[str, Any] = Field(validation_alias=AliasChoices("formula", "expression"))
    valid_from: date = Field(default_factory=date.today)
    valid_to: date | None = None

    @field_validator("formula")
    @classmethod
    def formula_is_nonempty_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("La fórmula debe contener una expresión DSL")
        return value

    @field_validator("valid_to")
    @classmethod
    def validity_is_inclusive(cls, value: date | None, info):
        start = info.data.get("valid_from")
        if value is not None and start is not None and value < start:
            raise ValueError("valid_to debe ser igual o posterior a valid_from")
        return value


class FormulaRead(BaseModel):
    id: int
    code: str
    description: str
    version: int
    formula: dict[str, Any]
    status: str
    valid_from: date
    valid_to: date | None


class AiProposalRead(ORMModel):
    id: int
    organization_id: int
    document_id: str
    document_hash: str | None
    title: str | None
    raw_json: Any
    validation_json: Any | None
    status: str
    approved_by: int | None
    approved_at: datetime | None
    published_formula_id: int | None
    created_at: datetime


class AiProposalPublishRead(AiProposalRead):
    formula_id: int
    formula_version_id: int
    formula_status: str


class PayrollRunInput(BaseModel):
    company_id: int
    code: str = Field(min_length=1, max_length=80)
    period_start: date
    period_end: date
    run_type: str = Field(default="MONTHLY", max_length=40)

    @field_validator("period_end")
    @classmethod
    def end_not_before_start(cls, value: date, info):
        start = info.data.get("period_start")
        if start is not None and value < start:
            raise ValueError("period_end debe ser igual o posterior a period_start")
        return value


class PayrollRunRead(ORMModel):
    id: int
    organization_id: int
    company_id: int
    code: str
    period_start: date
    period_end: date
    run_type: str
    status: str
    ruleset_id: int | None


