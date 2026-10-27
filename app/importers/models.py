"""Esquemas Pydantic de filas y resultados de importacion.

``valid_rows`` contiene instancias de :class:`EmployeeRow` o
:class:`NoveltyRow`. Los modelos aceptan acceso por atributo y tambien por
clave (``row["legajo"]``) para facilitar su uso desde capas que trabajan con
diccionarios.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.importers.parsing import (
    clean_legajo,
    clean_text,
    contains_html_chars,
    is_valid_cuil,
    is_valid_email,
    normalize_cuil,
    normalize_naturaleza,
    normalize_tipo,
    parse_date,
    parse_decimal,
    parse_periodo,
    parse_quincena,
)

ImportKind = Literal["employees", "novelties"]


class DictAccessMixin:
    """Acceso por atributo y por clave para facilitar integraciones."""

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class RowModel(DictAccessMixin, BaseModel):
    """Base de las filas importadas con acceso compatible con diccionarios."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


def _required_text(value: Any, field_name: str) -> str:
    text = clean_text(value)
    if text is None:
        raise ValueError(f"El campo '{field_name}' es obligatorio.")
    if contains_html_chars(text):
        raise ValueError(f"El campo '{field_name}' contiene caracteres no permitidos (< >).")
    return text


def _reject_html_optional(value: Any, field_name: str) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    if contains_html_chars(text):
        raise ValueError(f"El campo '{field_name}' contiene caracteres no permitidos (< >).")
    return text


class EmployeeRow(RowModel):
    """Fila valida de un empleado."""

    legajo: str = Field(min_length=1, max_length=50)
    apellido: str = Field(min_length=1, max_length=120)
    nombre: str = Field(min_length=1, max_length=120)
    cuil: str
    fecha_ingreso: date
    categoria: str | None = Field(default=None, max_length=120)
    convenio: str | None = Field(default=None, max_length=120)
    email: str | None = None

    @field_validator("legajo", mode="before")
    @classmethod
    def _normalize_legajo(cls, value: Any) -> str:
        legajo = clean_legajo(value)
        if legajo is None:
            raise ValueError("El campo 'legajo' es obligatorio.")
        if contains_html_chars(legajo):
            raise ValueError("El campo 'legajo' contiene caracteres no permitidos (< >).")
        return legajo

    @field_validator("apellido", "nombre", mode="before")
    @classmethod
    def _normalize_name(cls, value: Any, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("cuil", mode="before")
    @classmethod
    def _normalize_cuil(cls, value: Any) -> str:
        cuil = normalize_cuil(value)
        if cuil is None or not is_valid_cuil(cuil):
            raise ValueError(
                "El CUIL no es valido o no coincide su digito verificador. "
                "Se esperan 11 digitos (p. ej. 20-12345678-6)."
            )
        return cuil

    @field_validator("fecha_ingreso", mode="before")
    @classmethod
    def _normalize_fecha(cls, value: Any) -> date:
        parsed = parse_date(value)
        if parsed is None:
            raise ValueError("La fecha de ingreso no es valida.")
        return parsed

    @field_validator("categoria", "convenio", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any, info: Any) -> str | None:
        return _reject_html_optional(value, info.field_name)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: Any) -> str | None:
        email = clean_text(value)
        if email is None:
            return None
        if contains_html_chars(email):
            raise ValueError("El campo 'email' contiene caracteres no permitidos (< >).")
        if not is_valid_email(email):
            raise ValueError("El email no es valido.")
        return email


class NoveltyRow(RowModel):
    """Fila valida de una novedad."""

    legajo: str = Field(min_length=1, max_length=50)
    periodo: str = Field(pattern=r"^\d{6}$")
    tipo: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    cantidad: Decimal | None = None
    importe: Decimal | None = None
    observacion: str | None = None
    # B-43: naturaleza por novedad (default remunerativa, como antes) y
    # quincena opcional 1/2. Sin migracion: la naturaleza se persiste en
    # PayrollNovelty.kind; la quincena solo se valida y distingue duplicados.
    naturaleza: str = "REMUNERATIVE"
    quincena: int | None = None

    @field_validator("legajo", mode="before")
    @classmethod
    def _normalize_legajo(cls, value: Any) -> str:
        legajo = clean_legajo(value)
        if legajo is None:
            raise ValueError("El campo 'legajo' es obligatorio.")
        if contains_html_chars(legajo):
            raise ValueError("El campo 'legajo' contiene caracteres no permitidos (< >).")
        return legajo

    @field_validator("periodo", mode="before")
    @classmethod
    def _normalize_periodo(cls, value: Any) -> str:
        periodo = parse_periodo(value)
        if periodo is None:
            raise ValueError("El periodo debe tener formato AAAAMM o ser una fecha valida.")
        return periodo

    @field_validator("tipo", mode="before")
    @classmethod
    def _normalize_tipo(cls, value: Any) -> str:
        tipo = normalize_tipo(value)
        if tipo is None:
            raise ValueError("El tipo de novedad no es valido.")
        return tipo

    @field_validator("cantidad", "importe", mode="before")
    @classmethod
    def _normalize_decimal(cls, value: Any, info: Any) -> Decimal | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        places = 2 if info.field_name == "importe" else None
        number = parse_decimal(value, places=places)
        if number is None:
            label = "importe" if info.field_name == "importe" else "cantidad"
            raise ValueError(f"El {label} no es un numero valido.")
        return number

    @field_validator("observacion", mode="before")
    @classmethod
    def _normalize_observacion(cls, value: Any) -> str | None:
        return _reject_html_optional(value, "observacion")

    @field_validator("naturaleza", mode="before")
    @classmethod
    def _normalize_naturaleza(cls, value: Any) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return "REMUNERATIVE"
        naturaleza = normalize_naturaleza(value)
        if naturaleza is None:
            raise ValueError("La naturaleza no es valida (R/NR/D/C/AUX).")
        return naturaleza

    @field_validator("quincena", mode="before")
    @classmethod
    def _normalize_quincena(cls, value: Any) -> int | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        quincena = parse_quincena(value)
        if quincena is None:
            raise ValueError("La quincena debe ser 1 o 2.")
        return quincena


class RowError(DictAccessMixin, BaseModel):
    """Error de una fila, opcionalmente asociado a un campo."""

    row: int = Field(ge=0)
    field: str | None = None
    code: str
    message: str
    value: str | None = None


class DuplicateRow(DictAccessMixin, BaseModel):
    """Fila duplicada respecto de una fila anterior."""

    row: int = Field(ge=1)
    first_row: int = Field(ge=1)
    key: str
    message: str


class ImportOutcome(DictAccessMixin, BaseModel):
    """Base comun de preview y resultado."""

    kind: ImportKind
    total: int = Field(ge=0)
    valid_rows: list[EmployeeRow | NoveltyRow] = Field(default_factory=list)
    errors: list[RowError] = Field(default_factory=list)
    duplicates: list[DuplicateRow] = Field(default_factory=list)
    dry_run: bool = True

    @property
    def valid_count(self) -> int:
        return len(self.valid_rows)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)


class ImportPreview(ImportOutcome):
    """Resultado de ``analyze_file``; nunca persiste datos."""

    mapping: dict[str, str | None] = Field(default_factory=dict)
    missing_columns: list[str] = Field(default_factory=list)
    # B-44/B-76: avisos que no bloquean (columnas extra, hojas ignoradas).
    warnings: list[RowError] = Field(default_factory=list)


class ImportResult(ImportOutcome):
    """Resultado de ``import_rows``; puro, siempre en modo dry-run."""


def model_validation_errors(exc: ValidationError, row: int) -> list[RowError]:
    """Convierte un ``ValidationError`` de Pydantic a errores por campo."""
    result: list[RowError] = []
    for error in exc.errors():
        location = error.get("loc") or ()
        field = str(location[0]) if location else None
        message = str(error.get("msg", "Valor invalido."))
        result.append(
            RowError(
                row=row,
                field=field,
                code="valor_invalido",
                message=message,
            )
        )
    return result
