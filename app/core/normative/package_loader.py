"""Validated, idempotent import of CCT catalogs into the existing tables.

The loader is deliberately conservative:

* it validates the whole package before writing anything;
* it never deletes rows, so historical scales and parameters are preserved;
* it matches existing rows by natural key (CCT code/year, category code,
  scale category/effective date, parameter code/date/version and document
  checksum/path/URL);
* it never commits the session.  Callers decide when to commit.

The real package at ``normative/cct/catalog.json`` is optional.  Without it,
callers (and tests) can supply any catalog that follows the schema documented
in :func:`load_cct_catalog`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    NormativeDocument,
    NormativeParameter,
    SalaryScale,
)

_EMPTY_CHECKSUMS = frozenset(
    {
        "",
        "none",
        "n/a",
        "na",
        "missing",
        "not_available",
        "not-available",
        "pending",
        "unknown",
        "unverified",
    }
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_NUMERIC_18_4_MAX = Decimal("99999999999999.9999")
_NUMERIC_18_4_MIN = Decimal("-99999999999999.9999")


class PackageValidationError(ValueError):
    """Raised when a package fails schema or consistency validation."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(dict.fromkeys(errors))
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True, slots=True)
class CatalogDocument:
    """A source document referenced by a CCT or a parameter."""

    key: str
    title: str
    document_type: str
    source_url: str | None = None
    file_path: str | None = None
    checksum: str | None = None
    published_at: date | None = None


@dataclass(frozen=True, slots=True)
class CatalogCategory:
    code: str
    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogScale:
    category_code: str
    amount: Decimal
    valid_from: date
    valid_to: date | None = None
    additional: Decimal = Decimal("0")
    source: str = ""
    version: int = 1
    status: str = "unverified"
    # B-02: "basico" (remunerative base) vs "conformado" (total including the
    # non-remunerative part, which is split into ``additional`` on load).
    amount_type: str = "basico"


@dataclass(frozen=True, slots=True)
class CatalogParameter:
    jurisdiction: str
    code: str
    value: Decimal
    valid_from: date
    valid_to: date | None = None
    published_at: date | None = None
    version: int = 1
    source: str = ""
    document_key: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogCct:
    code: str
    year: int
    name: str
    activity: str | None
    scope: str | None
    source_urls: tuple[str, ...]
    pdf_path: str | None
    checksum: str | None
    pdf_status: str
    published_at: date | None
    categories: tuple[CatalogCategory, ...]
    scales: tuple[CatalogScale, ...]
    parameters: tuple[CatalogParameter, ...]
    document_key: str | None


@dataclass(frozen=True, slots=True)
class CatalogPackage:
    ccts: tuple[CatalogCct, ...]
    parameters: tuple[CatalogParameter, ...]
    documents: tuple[CatalogDocument, ...]
    warnings: tuple[str, ...]


@dataclass(slots=True)
class LoadStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged

    def record(self, action: str) -> None:
        if action == "created":
            self.created += 1
        elif action == "updated":
            self.updated += 1
        else:
            self.unchanged += 1

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "total": self.total,
        }


@dataclass(slots=True)
class PackageLoadResult:
    """Summary of a dry-run or committed package import.

    In dry-run mode ``created``/``updated`` mean *would be* created/updated.
    No row is written in that mode.
    """

    dry_run: bool
    agreements: LoadStats = field(default_factory=LoadStats)
    categories: LoadStats = field(default_factory=LoadStats)
    scales: LoadStats = field(default_factory=LoadStats)
    parameters: LoadStats = field(default_factory=LoadStats)
    documents: LoadStats = field(default_factory=LoadStats)
    catalog_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def created(self) -> int:
        return (
            self.agreements.created
            + self.categories.created
            + self.scales.created
            + self.parameters.created
            + self.documents.created
        )

    @property
    def updated(self) -> int:
        return (
            self.agreements.updated
            + self.categories.updated
            + self.scales.updated
            + self.parameters.updated
            + self.documents.updated
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "catalog_codes": list(self.catalog_codes),
            "agreements": self.agreements.as_dict(),
            "categories": self.categories.as_dict(),
            "scales": self.scales.as_dict(),
            "parameters": self.parameters.as_dict(),
            "documents": self.documents.as_dict(),
            "summary": {"created": self.created, "updated": self.updated},
            "warnings": list(self.warnings),
        }


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            value = mapping[key]
            if value is not None:
                return value
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _read_text(
    raw: Mapping[str, Any],
    keys: tuple[str, ...],
    path: str,
    errors: list[str],
    *,
    required: bool = False,
    max_length: int | None = None,
    default: str | None = None,
) -> str | None:
    value = _text(_first(raw, *keys))
    if value is None:
        if required:
            errors.append(f"{path}: falta el campo obligatorio '{keys[0]}'")
        return default
    if max_length is not None and len(value) > max_length:
        errors.append(f"{path}.{keys[0]}: supera {max_length} caracteres")
        return None
    return value


def _read_date(
    raw: Mapping[str, Any],
    keys: tuple[str, ...],
    path: str,
    errors: list[str],
    *,
    required: bool = False,
) -> date | None:
    value = _first(raw, *keys)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors.append(f"{path}: falta la fecha obligatoria '{keys[0]}'")
        return None
    if isinstance(value, datetime):
        errors.append(f"{path}.{keys[0]}: debe ser una fecha, no un datetime")
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            errors.append(f"{path}.{keys[0]}: fecha ISO inválida {value!r}")
            return None
    errors.append(f"{path}.{keys[0]}: fecha inválida")
    return None


def _read_decimal(
    raw: Mapping[str, Any],
    keys: tuple[str, ...],
    path: str,
    errors: list[str],
    *,
    required: bool = False,
    minimum: Decimal | None = None,
    label: str = "valor",
) -> Decimal | None:
    value = _first(raw, *keys)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors.append(f"{path}: falta el {label} obligatorio '{keys[0]}'")
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        errors.append(f"{path}.{keys[0]}: el {label} debe ser un Decimal finito")
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors.append(f"{path}.{keys[0]}: el {label} {value!r} no es un Decimal válido")
        return None
    if not number.is_finite():
        errors.append(f"{path}.{keys[0]}: el {label} debe ser un Decimal finito")
        return None
    if number < _NUMERIC_18_4_MIN or number > _NUMERIC_18_4_MAX:
        errors.append(
            f"{path}.{keys[0]}: el {label} excede el rango Numeric(18, 4) de la base"
        )
        return None
    if minimum is not None and number < minimum:
        errors.append(f"{path}.{keys[0]}: el {label} no puede ser menor que {minimum}")
        return None
    return number


def _read_int(
    raw: Mapping[str, Any],
    keys: tuple[str, ...],
    path: str,
    errors: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    value = _first(raw, *keys)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        errors.append(f"{path}.{keys[0]}: se esperaba un entero")
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        errors.append(f"{path}.{keys[0]}: se esperaba un entero")
        return None
    if minimum is not None and number < minimum:
        errors.append(f"{path}.{keys[0]}: debe ser mayor o igual a {minimum}")
        return None
    if maximum is not None and number > maximum:
        errors.append(f"{path}.{keys[0]}: debe ser menor o igual a {maximum}")
        return None
    return number


def _read_sequence(raw: Mapping[str, Any], keys: tuple[str, ...], path: str, errors: list[str]) -> list[Any]:
    value = _first(raw, *keys)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    errors.append(f"{path}.{keys[0]}: debe ser una lista")
    return []


def _read_urls(raw: Mapping[str, Any], path: str, errors: list[str]) -> tuple[str, ...]:
    value = _first(raw, "source_urls", "source_url", "urls", "fuentes")
    if value is None:
        return ()
    if isinstance(value, str):
        items: list[Any] = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    elif isinstance(value, Mapping):
        items = list(value.values())
    else:
        errors.append(f"{path}.source_urls: debe ser una lista, un objeto o una cadena")
        return ()
    urls: list[str] = []
    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            text = _text(_first(item, "url", "href", "link"))
        else:
            text = _text(item)
        if (
            text is None
            or len(text) > 1000
            or not text.lower().startswith(("http://", "https://"))
        ):
            errors.append(f"{path}.source_urls[{index}]: URL inválida")
            continue
        if text not in urls:
            urls.append(text)
    return tuple(urls)


def _read_checksum(raw: Mapping[str, Any], path: str, errors: list[str]) -> str | None:
    value = _text(_first(raw, "pdf_sha256", "sha256", "sha256_pdf", "checksum", "hash"))
    if value is None:
        return None
    if value.lower().startswith("sha256:"):
        value = value.split(":", 1)[1].strip()
    if value.lower() in _EMPTY_CHECKSUMS:
        return None
    if not _SHA256.fullmatch(value):
        errors.append(f"{path}: el checksum SHA-256 no es válido")
        return None
    return value.lower()


def _normalize_document_path(value: Any, path: str, errors: list[str]) -> str | None:
    text = _text(value)
    if text is None:
        return None
    if len(text) > 1000:
        errors.append(f"{path}: la ruta del documento supera 1000 caracteres")
        return None
    normalized = text.replace("\\", "/")
    if _WINDOWS_ABSOLUTE.match(normalized) or PurePosixPath(normalized).is_absolute():
        errors.append(f"{path}: pdf_path debe ser relativo al repositorio")
        return None
    candidate = PurePosixPath(normalized)
    if ".." in candidate.parts:
        errors.append(f"{path}: pdf_path no puede salir del repositorio")
        return None
    return candidate.as_posix()


def _has_source(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, (list, tuple)):
        return bool(value)
    return False


def _source_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        parts = [str(item).strip() for item in value.values() if item is not None and _text(str(item))]
        return " | ".join(parts)
    return ""


def _document_type(file_path: str | None) -> str:
    if file_path is None:
        return "cct"
    lowered = file_path.lower()
    if lowered.endswith(".pdf"):
        return "cct_pdf"
    if lowered.endswith((".html", ".htm")):
        return "cct_html"
    return "cct"


def _document_key(checksum: str | None, file_path: str | None, source_url: str | None) -> str:
    if checksum is not None:
        return f"sha256:{checksum}"
    if file_path is not None:
        return f"path:{file_path}"
    return f"url:{source_url}"


def _build_document(
    raw: Mapping[str, Any],
    path: str,
    errors: list[str],
    *,
    default_title: str,
    default_type: str,
    require_source: bool,
) -> CatalogDocument | None:
    urls = _read_urls(raw, path, errors)
    file_path = _normalize_document_path(
        _first(raw, "pdf_path", "file_path", "document_path", "ruta_pdf", "archivo"),
        path,
        errors,
    )
    checksum = _read_checksum(raw, path, errors)
    if not urls and file_path is None and checksum is None:
        if require_source:
            errors.append(f"{path}: el CCT debe declarar source_urls o pdf_path como fuente")
        return None
    title = _read_text(
        raw,
        ("document_title", "source_title", "titulo_documento", "title"),
        path,
        errors,
        max_length=240,
    ) or default_title
    if len(title) > 240:
        errors.append(f"{path}: el título del documento supera 240 caracteres")
        title = title[:240]
    document_type = _read_text(
        raw, ("document_type", "tipo_documento"), path, errors, max_length=60
    ) or default_type
    published_at = _read_date(
        raw,
        (
            "published_at",
            "publication_date",
            "source_date",
            "fecha_publicacion",
            "publicado_el",
            "pdf_published_at",
        ),
        path,
        errors,
    )
    source_url = urls[0] if urls else None
    key = _document_key(checksum, file_path, source_url)
    return CatalogDocument(
        key=key,
        title=title,
        document_type=document_type,
        source_url=source_url,
        file_path=file_path,
        checksum=checksum,
        published_at=published_at,
    )


def _derive_year(code: str) -> int | None:
    if "/" not in code:
        return None
    suffix = code.rsplit("/", 1)[1].strip()
    if not suffix.isdigit():
        return None
    if len(suffix) == 4:
        year = int(suffix)
        return year if 1900 <= year <= 9999 else None
    if len(suffix) == 2:
        value = int(suffix)
        # CCT codes use two-digit years: 04 -> 2004, 75 -> 1975.
        return (2000 if value < 30 else 1900) + value
    return None


def _read_categories(
    raw: Mapping[str, Any],
    path: str,
    errors: list[str],
    warnings: list[str],
) -> tuple[tuple[CatalogCategory, ...], dict[str, CatalogCategory]]:
    items = _read_sequence(raw, ("categories", "categorias"), path, errors)
    categories: list[CatalogCategory] = []
    by_code: dict[str, CatalogCategory] = {}
    for index, item in enumerate(items):
        item_path = f"{path}.categories[{index}]"
        name: str | None
        if isinstance(item, str):
            code = _text(item)
            if code is None:
                errors.append(f"{item_path}: código de categoría vacío")
                continue
            name = code
            description = None
        elif isinstance(item, Mapping):
            code = _read_text(
                item,
                ("code", "codigo", "categoria", "category_code", "codigo_categoria"),
                item_path,
                errors,
                required=True,
                max_length=40,
            )
            name = _read_text(
                item,
                ("name", "nombre", "denominacion", "descripcion_corta"),
                item_path,
                errors,
                max_length=160,
            )
            description = _read_text(item, ("description", "descripcion"), item_path, errors)
        else:
            errors.append(f"{item_path}: debe ser un objeto o un código")
            continue
        if code is None:
            continue
        if name is None:
            name = code
            warnings.append(f"{item_path}: categoría sin nombre; se usa el código {code!r}")
        key = code.casefold()
        if key in by_code:
            errors.append(f"{item_path}: código de categoría duplicado {code!r}")
            continue
        category = CatalogCategory(code=code, name=name, description=description)
        by_code[key] = category
        categories.append(category)
    return tuple(categories), by_code


def _resolve_category_code(
    categories: Mapping[str, CatalogCategory], value: str
) -> str | None:
    direct = categories.get(value.casefold())
    if direct is not None:
        return direct.code
    for category in categories.values():
        if category.name.casefold() == value.casefold():
            return category.code
    return None


def _read_scales(
    raw: Mapping[str, Any],
    path: str,
    categories: Mapping[str, CatalogCategory],
    errors: list[str],
    warnings: list[str],
) -> tuple[CatalogScale, ...]:
    items = _read_sequence(
        raw, ("salary_scales", "scales", "escalas", "escalas_salariales"), path, errors
    )
    scales: list[CatalogScale] = []
    for index, item in enumerate(items):
        item_path = f"{path}.salary_scales[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{item_path}: debe ser un objeto")
            continue
        category_raw = _first(item, "category", "category_code", "categoria", "codigo_categoria")
        category_code: str | None
        if isinstance(category_raw, Mapping):
            category_code = _read_text(
                category_raw,
                ("code", "codigo", "categoria", "category_code"),
                f"{item_path}.category",
                errors,
                max_length=40,
            )
            if category_code is None:
                name_hint = _read_text(
                    category_raw,
                    ("name", "nombre"),
                    f"{item_path}.category",
                    errors,
                    max_length=160,
                )
                if name_hint is not None:
                    category_code = _resolve_category_code(categories, name_hint)
        else:
            category_code = _text(category_raw)
            if category_code is not None:
                category_code = _resolve_category_code(categories, category_code)
        if category_code is None:
            errors.append(f"{item_path}: falta o no se pudo resolver la categoría de la escala")
        elif category_code.casefold() not in categories:
            errors.append(f"{item_path}: la categoría {category_code!r} no está declarada")
        status = _read_text(item, ("status", "estado"), item_path, errors, max_length=60)
        if status is not None and status.casefold() in {"unverified", "pending", "estimated"}:
            warnings.append(f"{item_path}: escala sin importe verificado; se omite del paquete")
            continue
        amount = _read_decimal(
            item,
            ("amount", "importe", "base_salary", "monthly_salary", "salary", "monto"),
            item_path,
            errors,
            required=False,
            minimum=Decimal("0"),
            label="importe",
        )
        if amount is None:
            estimated = _first(item, "estimated_value", "valor_estimado")
            if estimated is not None:
                warnings.append(
                    f"{item_path}: escala sin importe verificado; se omite del paquete"
                )
                continue
            errors.append(f"{item_path}: falta el importe obligatorio 'amount'")
        additional = _read_decimal(
            item,
            ("additional", "adicional", "no_remunerativo", "nr"),
            item_path,
            errors,
            minimum=Decimal("0"),
            label="adicional",
        )
        raw_amount_type = _text(_first(item, "amount_type", "tipo_importe", "tipo_monto", "tipo"))
        amount_type = _normalise_amount_type(raw_amount_type, item_path, errors)
        valid_from = _read_date(
            item,
            ("valid_from", "vigencia_desde", "desde", "from"),
            item_path,
            errors,
            required=True,
        )
        valid_to = _read_date(
            item,
            ("valid_to", "vigencia_hasta", "hasta", "to"),
            item_path,
            errors,
        )
        if valid_from is not None and valid_to is not None and valid_to < valid_from:
            errors.append(f"{item_path}: valid_to no puede ser anterior a valid_from (vigencia inclusiva)")
        source_value = _first(item, "source", "fuente")
        if not _has_source(source_value):
            errors.append(f"{item_path}: la escala debe declarar source/fuente")
        currency = _read_text(item, ("currency", "moneda"), item_path, errors, max_length=10)
        if currency is not None and currency.upper() != "ARS":
            errors.append(f"{item_path}: moneda no soportada {currency!r}; se esperaba ARS")
        version = _read_int(item, ("version", "versión"), item_path, errors, minimum=1) or 1
        if category_code is None or amount is None or valid_from is None:
            continue
        base_amount = amount
        extra = additional if additional is not None else Decimal("0")
        if amount_type == "conformado":
            if extra > 0:
                if extra > amount:
                    errors.append(
                        f"{item_path}: el adicional NR no puede superar el total conformado"
                    )
                    continue
                base_amount = amount - extra
            else:
                warnings.append(
                    f"{item_path}: la escala declara amount_type 'conformado' "
                    "sin desglose NR; se trata como básico hasta "
                    "completar el desglose (B-02)"
                )
        scales.append(
            CatalogScale(
                category_code=category_code,
                amount=base_amount,
                valid_from=valid_from,
                valid_to=valid_to,
                additional=extra,
                source=_source_text(source_value),
                version=version,
                status=status or "unverified",
                amount_type=amount_type,
            )
        )
    return tuple(scales)


def _normalise_amount_type(
    value: str | None, path: str, errors: list[str]
) -> str:
    """Validate the B-02 scale kind: base salary vs conformed total."""
    if value is None:
        return "basico"
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", value.strip().casefold())
        if not unicodedata.combining(char)
    )
    if text in {"basico", "básico"}:
        return "basico"
    if text == "conformado":
        return "conformado"
    errors.append(
        f"{path}: amount_type {value!r} inválido; se esperaba 'basico' o 'conformado'"
    )
    return "basico"


def _read_parameters(
    raw: Mapping[str, Any],
    path: str,
    errors: list[str],
    warnings: list[str],
    *,
    document_key: str | None = None,
) -> tuple[CatalogParameter, ...]:
    items = _read_sequence(
        raw,
        ("parameters", "parametros", "normative_parameters", "parametros_normativos"),
        path,
        errors,
    )
    parameters: list[CatalogParameter] = []
    for index, item in enumerate(items):
        item_path = f"{path}.parameters[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{item_path}: debe ser un objeto")
            continue
        jurisdiction = _read_text(
            item, ("jurisdiction", "jurisdiccion"), item_path, errors, max_length=80
        ) or "AR"
        code = _read_text(item, ("code", "codigo"), item_path, errors, required=True, max_length=100)
        value = _read_decimal(
            item,
            ("value", "valor", "amount", "importe"),
            item_path,
            errors,
            required=True,
            label="valor",
        )
        valid_from = _read_date(
            item,
            ("valid_from", "vigencia_desde", "desde", "from"),
            item_path,
            errors,
            required=True,
        )
        valid_to = _read_date(
            item,
            ("valid_to", "vigencia_hasta", "hasta", "to"),
            item_path,
            errors,
        )
        if valid_from is not None and valid_to is not None and valid_to < valid_from:
            errors.append(f"{item_path}: valid_to no puede ser anterior a valid_from (vigencia inclusiva)")
        version = _read_int(item, ("version", "versión"), item_path, errors, minimum=1) or 1
        published_at = _read_date(
            item,
            ("published_at", "publication_date", "fecha_publicacion"),
            item_path,
            errors,
        )
        source = _source_text(_first(item, "source", "fuente"))
        if source == "" and document_key is None:
            warnings.append(f"{item_path}: parámetro sin fuente documental explícita")
        if code is None or value is None or valid_from is None:
            continue
        parameters.append(
            CatalogParameter(
                jurisdiction=jurisdiction,
                code=code,
                value=value,
                valid_from=valid_from,
                valid_to=valid_to,
                published_at=published_at,
                version=version,
                source=source,
                document_key=document_key,
            )
        )
    return tuple(parameters)


def _ranges_overlap(
    left_from: date,
    left_to: date | None,
    right_from: date,
    right_to: date | None,
) -> bool:
    return (left_to is None or right_from <= left_to) and (
        right_to is None or left_from <= right_to
    )


def _validate_catalog(catalog: dict[str, Any]) -> CatalogPackage:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(catalog, Mapping):
        raise PackageValidationError(["El catálogo debe ser un objeto JSON"])

    raw_ccts = _first(catalog, "ccts", "agreements", "collective_agreements")
    if not isinstance(raw_ccts, (list, tuple)) or not raw_ccts:
        raise PackageValidationError(["El catálogo debe incluir 'ccts' como lista no vacía"])

    documents: dict[str, CatalogDocument] = {}

    def register_document(document: CatalogDocument, path: str) -> None:
        previous = documents.get(document.key)
        if previous is None:
            documents[document.key] = document
        elif previous != document:
            warnings.append(
                f"{path}: se reutiliza el documento {document.key} con metadatos distintos"
            )

    ccts: list[CatalogCct] = []
    seen_codes: set[str] = set()
    all_parameters: list[CatalogParameter] = []

    for index, raw in enumerate(raw_ccts):
        path = f"ccts[{index}]"
        if not isinstance(raw, Mapping):
            errors.append(f"{path}: debe ser un objeto")
            continue
        code = _read_text(
            raw, ("code", "codigo", "cct"), path, errors, required=True, max_length=40
        )
        name = _read_text(
            raw,
            ("name", "nombre", "denominacion", "nombre_cct"),
            path,
            errors,
            required=True,
            max_length=200,
        )
        if code is not None:
            code_key = code.casefold()
            if code_key in seen_codes:
                errors.append(f"{path}: código de CCT duplicado {code!r}")
                continue
            seen_codes.add(code_key)
        year = _read_int(raw, ("year", "anio", "año"), path, errors, minimum=1900, maximum=9999)
        if year is None and code is not None:
            year = _derive_year(code)
            if year is None:
                errors.append(f"{path}: no se pudo derivar el año desde el código {code!r}")
        if code is None or name is None or year is None:
            continue

        activity = _read_text(
            raw,
            ("activity", "actividad", "actividad_economica"),
            path,
            errors,
            max_length=160,
        )
        scope = _read_text(
            raw, ("scope", "alcance", "ambito", "ambito_aplicacion"), path, errors
        )
        source_urls = _read_urls(raw, path, errors)
        pdf_path = _normalize_document_path(
            _first(raw, "pdf_path", "file_path", "document_path", "ruta_pdf", "archivo"),
            path,
            errors,
        )
        document = _build_document(
            raw,
            path,
            errors,
            default_title=f"{name} ({code})",
            default_type=_document_type(pdf_path),
            require_source=True,
        )
        if document is not None:
            register_document(document, path)
        checksum = _read_checksum(raw, path, errors)
        pdf_status = (
            _read_text(raw, ("pdf_status", "estado_pdf"), path, errors, max_length=60)
            or "unverified"
        )
        if pdf_status.casefold() in {"verified", "verificado"} and checksum is None:
            errors.append(f"{path}: pdf_status 'verified' requiere un pdf_sha256 válido")
        published_at = _read_date(
            raw,
            (
                "published_at",
                "publication_date",
                "source_date",
                "fecha_publicacion",
                "publicado_el",
                "pdf_published_at",
            ),
            path,
            errors,
        )
        categories, category_map = _read_categories(raw, path, errors, warnings)
        scales = _read_scales(raw, path, category_map, errors, warnings)
        parameters = _read_parameters(
            raw,
            path,
            errors,
            warnings,
            document_key=document.key if document is not None else None,
        )
        all_parameters.extend(parameters)
        ccts.append(
            CatalogCct(
                code=code,
                year=year,
                name=name,
                activity=activity,
                scope=scope,
                source_urls=source_urls,
                pdf_path=pdf_path,
                checksum=checksum,
                pdf_status=pdf_status,
                published_at=published_at,
                categories=categories,
                scales=scales,
                parameters=parameters,
                document_key=document.key if document is not None else None,
            )
        )

    top_parameters = _read_parameters(
        catalog,
        "catalog",
        errors,
        warnings,
    )
    all_parameters.extend(top_parameters)

    _validate_scale_overlaps(ccts, errors)
    _validate_parameter_overlaps(all_parameters, errors)

    if errors:
        raise PackageValidationError(errors)
    return CatalogPackage(
        ccts=tuple(ccts),
        parameters=tuple(all_parameters),
        documents=tuple(documents.values()),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _validate_scale_overlaps(ccts: Iterable[CatalogCct], errors: list[str]) -> None:
    for cct in ccts:
        grouped: dict[str, list[CatalogScale]] = {}
        for scale in cct.scales:
            grouped.setdefault(scale.category_code.casefold(), []).append(scale)
        for category_code, scales in grouped.items():
            for left_index, left in enumerate(scales):
                for right in scales[left_index + 1 :]:
                    if _ranges_overlap(
                        left.valid_from, left.valid_to, right.valid_from, right.valid_to
                    ):
                        errors.append(
                            f"CCT {cct.code}: escalas superpuestas para {category_code} "
                            f"({left.valid_from}..{left.valid_to or 'abierta'} y "
                            f"{right.valid_from}..{right.valid_to or 'abierta'})"
                        )


def _validate_parameter_overlaps(
    parameters: Iterable[CatalogParameter], errors: list[str]
) -> None:
    grouped: dict[tuple[str, str], list[CatalogParameter]] = {}
    seen: set[tuple[str, str, date, int]] = set()
    for parameter in parameters:
        key = (parameter.jurisdiction.casefold(), parameter.code.casefold())
        identity = (key[0], key[1], parameter.valid_from, parameter.version)
        if identity in seen:
            errors.append(
                f"Parámetro duplicado {parameter.code!r} "
                f"({parameter.jurisdiction}, {parameter.valid_from}, v{parameter.version})"
            )
        seen.add(identity)
        grouped.setdefault(key, []).append(parameter)
    for (jurisdiction, code), versions in grouped.items():
        for left_index, left in enumerate(versions):
            for right in versions[left_index + 1 :]:
                if _ranges_overlap(
                    left.valid_from, left.valid_to, right.valid_from, right.valid_to
                ):
                    errors.append(
                        f"Parámetros superpuestos {code!r} ({jurisdiction}): "
                        f"{left.valid_from}..{left.valid_to or 'abierta'} y "
                        f"{right.valid_from}..{right.valid_to or 'abierta'}"
                    )


@dataclass(slots=True)
class _DocumentPlan:
    spec: CatalogDocument
    existing: NormativeDocument | None
    action: str


@dataclass(slots=True)
class _ScalePlan:
    spec: CatalogScale
    existing: SalaryScale | None
    action: str
    document: _DocumentPlan | None


@dataclass(slots=True)
class _CategoryPlan:
    spec: CatalogCategory
    existing: AgreementCategory | None
    action: str
    scales: list[_ScalePlan] = field(default_factory=list)


@dataclass(slots=True)
class _AgreementPlan:
    spec: CatalogCct
    existing: CollectiveAgreement | None
    action: str
    categories: list[_CategoryPlan] = field(default_factory=list)


@dataclass(slots=True)
class _ParameterPlan:
    spec: CatalogParameter
    existing: NormativeParameter | None
    action: str
    document: _DocumentPlan | None


def _action(existing: Any | None, changed: bool) -> str:
    if existing is None:
        return "created"
    return "updated" if changed else "unchanged"


def _find_document(session: Session, spec: CatalogDocument) -> NormativeDocument | None:
    if spec.checksum is not None:
        row = session.scalar(
            select(NormativeDocument).where(NormativeDocument.checksum == spec.checksum)
        )
        if row is not None:
            return row
    if spec.file_path is not None:
        row = session.scalar(
            select(NormativeDocument)
            .where(NormativeDocument.file_path == spec.file_path)
            .order_by(NormativeDocument.id)
        )
        if row is not None:
            return row
    if spec.source_url is not None:
        return session.scalar(
            select(NormativeDocument)
            .where(NormativeDocument.source_url == spec.source_url)
            .order_by(NormativeDocument.id)
        )
    return None


def _document_changed(row: NormativeDocument, spec: CatalogDocument) -> bool:
    return (
        row.title != spec.title
        or row.document_type != spec.document_type
        or (spec.source_url is not None and row.source_url != spec.source_url)
        or (spec.file_path is not None and row.file_path != spec.file_path)
        or (spec.checksum is not None and row.checksum != spec.checksum)
        or (spec.published_at is not None and row.published_at != spec.published_at)
    )


def _agreement_changed(row: CollectiveAgreement, spec: CatalogCct) -> bool:
    return (
        row.name != spec.name
        or not row.active
        or (spec.activity is not None and row.activity != spec.activity)
        or (spec.scope is not None and row.scope != spec.scope)
    )


def _category_changed(row: AgreementCategory, spec: CatalogCategory) -> bool:
    return row.name != spec.name or (
        spec.description is not None and row.description != spec.description
    )


def _expected_document_id(plan: _DocumentPlan | None) -> int | None:
    if plan is None or plan.existing is None:
        return None
    return plan.existing.id


def _scale_changed(row: SalaryScale, spec: CatalogScale, plan: _DocumentPlan | None) -> bool:
    if (
        row.base_salary != spec.amount
        or row.additional != spec.additional
        or row.valid_to != spec.valid_to
        or row.amount_type != spec.amount_type
    ):
        return True
    if plan is not None and plan.action == "created":
        return True
    expected_document_id = _expected_document_id(plan)
    return expected_document_id is not None and row.source_document_id != expected_document_id


def _parameter_changed(
    row: NormativeParameter, spec: CatalogParameter, plan: _DocumentPlan | None
) -> bool:
    if (
        row.value != spec.value
        or row.valid_to != spec.valid_to
        or (spec.published_at is not None and row.published_at != spec.published_at)
    ):
        return True
    if plan is not None and plan.action == "created":
        return True
    expected_document_id = _expected_document_id(plan)
    return expected_document_id is not None and row.source_document_id != expected_document_id


def _assert_no_scale_overlap(
    session: Session,
    category_id: int,
    spec: CatalogScale,
    *,
    exclude_id: int | None,
) -> None:
    rows = session.scalars(
        select(SalaryScale).where(SalaryScale.category_id == category_id)
    ).all()
    for row in rows:
        if exclude_id is not None and row.id == exclude_id:
            continue
        if _ranges_overlap(spec.valid_from, spec.valid_to, row.valid_from, row.valid_to):
            raise PackageValidationError(
                [
                    f"La escala {spec.category_code} "
                    f"{spec.valid_from}..{spec.valid_to or 'abierta'} se solapa con "
                    f"la escala existente {row.valid_from}..{row.valid_to or 'abierta'}"
                ]
            )


def _assert_no_parameter_overlap(
    session: Session,
    spec: CatalogParameter,
    *,
    exclude_id: int | None,
) -> None:
    rows = session.scalars(
        select(NormativeParameter).where(
            NormativeParameter.jurisdiction == spec.jurisdiction,
            NormativeParameter.code == spec.code,
        )
    ).all()
    for row in rows:
        if exclude_id is not None and row.id == exclude_id:
            continue
        if _ranges_overlap(spec.valid_from, spec.valid_to, row.valid_from, row.valid_to):
            raise PackageValidationError(
                [
                    f"El parámetro {spec.code!r} "
                    f"{spec.valid_from}..{spec.valid_to or 'abierta'} se solapa con "
                    f"la versión existente {row.valid_from}..{row.valid_to or 'abierta'}"
                ]
            )


def _build_plans(
    session: Session,
    package: CatalogPackage,
    result: PackageLoadResult,
) -> tuple[list[_AgreementPlan], list[_ParameterPlan], dict[str, _DocumentPlan]]:
    document_plans: dict[str, _DocumentPlan] = {}
    for spec in package.documents:
        existing = _find_document(session, spec)
        action = _action(existing, _document_changed(existing, spec) if existing else False)
        document_plans[spec.key] = _DocumentPlan(spec=spec, existing=existing, action=action)
        result.documents.record(action)

    agreement_plans: list[_AgreementPlan] = []
    for cct in package.ccts:
        existing_agreement = session.scalar(
            select(CollectiveAgreement).where(
                CollectiveAgreement.code == cct.code,
                CollectiveAgreement.year == cct.year,
            )
        )
        agreement_action = _action(
            existing_agreement,
            _agreement_changed(existing_agreement, cct) if existing_agreement else False,
        )
        result.agreements.record(agreement_action)
        agreement_plan = _AgreementPlan(
            spec=cct, existing=existing_agreement, action=agreement_action
        )
        scales_by_category: dict[str, list[CatalogScale]] = {}
        for scale in cct.scales:
            scales_by_category.setdefault(scale.category_code.casefold(), []).append(scale)
        for category in cct.categories:
            existing_category = None
            if existing_agreement is not None:
                existing_category = session.scalar(
                    select(AgreementCategory).where(
                        AgreementCategory.agreement_id == existing_agreement.id,
                        AgreementCategory.code == category.code,
                    )
                )
            category_action = _action(
                existing_category,
                _category_changed(existing_category, category) if existing_category else False,
            )
            result.categories.record(category_action)
            category_plan = _CategoryPlan(
                spec=category, existing=existing_category, action=category_action
            )
            for scale in scales_by_category.get(category.code.casefold(), []):
                existing_scale = None
                if existing_category is not None:
                    existing_scale = session.scalar(
                        select(SalaryScale).where(
                            SalaryScale.category_id == existing_category.id,
                            SalaryScale.valid_from == scale.valid_from,
                        )
                    )
                    _assert_no_scale_overlap(
                        session,
                        existing_category.id,
                        scale,
                        exclude_id=existing_scale.id if existing_scale is not None else None,
                    )
                document_plan = (
                    document_plans.get(cct.document_key) if cct.document_key else None
                )
                scale_action = _action(
                    existing_scale,
                    _scale_changed(existing_scale, scale, document_plan)
                    if existing_scale
                    else False,
                )
                result.scales.record(scale_action)
                category_plan.scales.append(
                    _ScalePlan(
                        spec=scale,
                        existing=existing_scale,
                        action=scale_action,
                        document=document_plan,
                    )
                )
            agreement_plan.categories.append(category_plan)
        agreement_plans.append(agreement_plan)

    parameter_plans: list[_ParameterPlan] = []
    for parameter in package.parameters:
        existing_parameter = session.scalar(
            select(NormativeParameter).where(
                NormativeParameter.jurisdiction == parameter.jurisdiction,
                NormativeParameter.code == parameter.code,
                NormativeParameter.valid_from == parameter.valid_from,
                NormativeParameter.version == parameter.version,
            )
        )
        _assert_no_parameter_overlap(
            session,
            parameter,
            exclude_id=existing_parameter.id if existing_parameter is not None else None,
        )
        document_plan = (
            document_plans.get(parameter.document_key) if parameter.document_key else None
        )
        parameter_action = _action(
            existing_parameter,
            _parameter_changed(existing_parameter, parameter, document_plan)
            if existing_parameter
            else False,
        )
        result.parameters.record(parameter_action)
        parameter_plans.append(
            _ParameterPlan(
                spec=parameter,
                existing=existing_parameter,
                action=parameter_action,
                document=document_plan,
            )
        )
    return agreement_plans, parameter_plans, document_plans


def _apply_documents(session: Session, plans: Mapping[str, _DocumentPlan]) -> None:
    for plan in plans.values():
        spec = plan.spec
        if plan.action == "created":
            row = NormativeDocument(
                title=spec.title,
                document_type=spec.document_type,
                source_url=spec.source_url,
                file_path=spec.file_path,
                checksum=spec.checksum,
                published_at=spec.published_at,
            )
            session.add(row)
            plan.existing = row
        elif plan.action == "updated" and plan.existing is not None:
            row = plan.existing
            row.title = spec.title
            row.document_type = spec.document_type
            if spec.source_url is not None:
                row.source_url = spec.source_url
            if spec.file_path is not None:
                row.file_path = spec.file_path
            if spec.checksum is not None:
                row.checksum = spec.checksum
            if spec.published_at is not None:
                row.published_at = spec.published_at
    session.flush()


def _apply_agreements(session: Session, plans: Iterable[_AgreementPlan]) -> None:
    for plan in plans:
        cct = plan.spec
        if plan.action == "created":
            row = CollectiveAgreement(
                code=cct.code,
                year=cct.year,
                name=cct.name,
                activity=cct.activity,
                scope=cct.scope,
                active=True,
            )
            session.add(row)
            plan.existing = row
        elif plan.action == "updated" and plan.existing is not None:
            row = plan.existing
            row.name = cct.name
            if cct.activity is not None:
                row.activity = cct.activity
            if cct.scope is not None:
                row.scope = cct.scope
            row.active = True
    session.flush()


def _apply_categories(session: Session, plans: Iterable[_AgreementPlan]) -> None:
    for agreement_plan in plans:
        agreement = agreement_plan.existing
        if agreement is None:
            raise RuntimeError("agreement plan was not applied before its categories")
        for plan in agreement_plan.categories:
            category = plan.spec
            if plan.action == "created":
                row = AgreementCategory(
                    agreement_id=agreement.id,
                    code=category.code,
                    name=category.name,
                    description=category.description,
                )
                session.add(row)
                plan.existing = row
            elif plan.action == "updated" and plan.existing is not None:
                row = plan.existing
                row.name = category.name
                if category.description is not None:
                    row.description = category.description
    session.flush()


def _apply_scales(session: Session, plans: Iterable[_AgreementPlan]) -> None:
    for agreement_plan in plans:
        for category_plan in agreement_plan.categories:
            category = category_plan.existing
            if category is None:
                raise RuntimeError("category plan was not applied before its scales")
            for plan in category_plan.scales:
                scale = plan.spec
                document_id = plan.document.existing.id if plan.document and plan.document.existing else None
                if plan.action == "created":
                    row = SalaryScale(
                        category_id=category.id,
                        valid_from=scale.valid_from,
                        valid_to=scale.valid_to,
                        base_salary=scale.amount,
                        additional=scale.additional,
                        amount_type=scale.amount_type,
                        source_document_id=document_id,
                    )
                    session.add(row)
                    plan.existing = row
                elif plan.action == "updated" and plan.existing is not None:
                    row = plan.existing
                    row.base_salary = scale.amount
                    row.additional = scale.additional
                    row.amount_type = scale.amount_type
                    row.valid_to = scale.valid_to
                    if document_id is not None:
                        row.source_document_id = document_id
    session.flush()


def _apply_parameters(session: Session, plans: Iterable[_ParameterPlan]) -> None:
    for plan in plans:
        parameter = plan.spec
        document_id = plan.document.existing.id if plan.document and plan.document.existing else None
        if plan.action == "created":
            row = NormativeParameter(
                jurisdiction=parameter.jurisdiction,
                code=parameter.code,
                value=parameter.value,
                valid_from=parameter.valid_from,
                valid_to=parameter.valid_to,
                published_at=parameter.published_at,
                version=parameter.version,
                source_document_id=document_id,
            )
            session.add(row)
            plan.existing = row
        elif plan.action == "updated" and plan.existing is not None:
            row = plan.existing
            row.value = parameter.value
            row.valid_to = parameter.valid_to
            if parameter.published_at is not None:
                row.published_at = parameter.published_at
            if document_id is not None:
                row.source_document_id = document_id
    session.flush()


def cct_coverage_map(
    catalog: Mapping[str, Any] | list[Any] | None,
) -> dict[str, dict[str, str | None]]:
    """Best-effort CCT coverage hook: ``{code: {"vigencia_hasta": ..., "status": ...}}``.

    Reads ``vigencia_hasta``/``status`` from the catalog when present and
    tolerates their absence (``None``). Never raises: garbage in, ``{}`` out.
    """

    def _pick(entry: Mapping[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = entry.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    try:
        if catalog is None:
            return {}
        if isinstance(catalog, Mapping):
            raw_ccts = catalog.get("ccts", catalog.get("agreements", []))
        elif isinstance(catalog, (list, tuple)):
            raw_ccts = catalog
        else:
            return {}
        coverage: dict[str, dict[str, str | None]] = {}
        for entry in raw_ccts or []:
            if not isinstance(entry, Mapping):
                continue
            code = _pick(entry, "code", "codigo", "cct")
            if code is None:
                continue
            coverage[code] = {
                "vigencia_hasta": _pick(
                    entry, "vigencia_hasta", "valid_to", "latest_verified_to"
                ),
                "status": _pick(entry, "status", "estado", "pdf_status"),
            }
        return coverage
    except Exception:
        return {}


def load_cct_catalog(
    session: Session,
    catalog: dict[str, Any] | list[Any],
    *,
    dry_run: bool = True,
) -> PackageLoadResult:
    """Validate and import a CCT catalog into the existing normative tables.

    The canonical catalog shape is::

        {
          "ccts": [
            {
              "code": "130/75",
              "name": "Empleados de Comercio",
              "activity": "Comercio",
              "scope": "...",
              "source_urls": ["https://..."],
              "pdf_path": "normative/cct/pdfs/130-75.pdf",
              "pdf_sha256": "<64 hex characters>",
              "pdf_status": "verified",
              "categories": [{"code": "ADMIN_A", "name": "Administrativo A"}],
              "salary_scales": [{
                "category": "ADMIN_A",
                "amount": "850000.00",
                "currency": "ARS",
                "valid_from": "2025-05-01",
                "valid_to": "2025-05-31",
                "source": "Resolución ... página 4",
                "status": "verified"
              }],
              "parameters": [{
                "code": "cct13075.seniority_rate",
                "value": "0.01",
                "valid_from": "2025-05-01",
                "valid_to": None,
                "version": 1,
                "source": "..."
              }]
            }
          ]
        }

    Spanish aliases (``codigo``, ``nombre``, ``categoria``, ``importe``,
    ``vigencia_desde``, ``vigencia_hasta``, ``fuente``, ``moneda``, etc.) are
    accepted because research catalogs are often written in Spanish.

    ``dry_run=True`` performs all schema, database-overlap and idempotency
    checks without writing anything.  The function never commits; when
    ``dry_run=False`` the caller must commit or roll back the session.
    """

    if isinstance(catalog, list):
        catalog = {"ccts": catalog}
    package = _validate_catalog(catalog)
    result = PackageLoadResult(
        dry_run=dry_run,
        catalog_codes=tuple(cct.code for cct in package.ccts),
        warnings=package.warnings,
    )
    agreement_plans, parameter_plans, document_plans = _build_plans(session, package, result)
    if not dry_run:
        _apply_documents(session, document_plans)
        _apply_agreements(session, agreement_plans)
        _apply_categories(session, agreement_plans)
        _apply_scales(session, agreement_plans)
        _apply_parameters(session, parameter_plans)
    return result
