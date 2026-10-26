"""Servicio puro de importacion de empleados y novedades.

El modulo no persiste nada: ``analyze_file`` arma un preview y ``import_rows``
revalida filas ya extraidas para obtener un resultado. Ambas funciones son
deterministas, no acceden a la base y no hacen llamadas de red.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from pydantic import ValidationError

from app.importers.mapping import (
    implied_type_for_header,
    missing_columns,
    resolve_mapping,
)
from app.importers.models import (
    DuplicateRow,
    EmployeeRow,
    ImportKind,
    ImportPreview,
    ImportResult,
    NoveltyRow,
    RowError,
    RowModel,
    model_validation_errors,
)
from app.importers.parsing import (
    clean_legajo,
    clean_text,
    is_blank,
    is_valid_cuil,
    is_valid_email,
    normalize_cuil,
    normalize_text,
    normalize_tipo,
    parse_date,
    parse_decimal,
    parse_periodo,
)
from app.importers.readers import Table, read_table

_KIND_ALIASES = {
    "employees": "employees",
    "employee": "employees",
    "empleados": "employees",
    "empleado": "employees",
    "novelties": "novelties",
    "novelty": "novelties",
    "novedades": "novelties",
    "novedad": "novelties",
}


def normalize_kind(kind: str) -> ImportKind:
    """Canonicaliza ``kind`` a ``employees`` o ``novelties``."""
    text = normalize_text(kind).replace(" ", "_")
    canonical = _KIND_ALIASES.get(text)
    if canonical is None:
        raise ValueError(
            "Tipo de importacion invalido. Se esperaba 'employees' o 'novelties'."
        )
    return cast(ImportKind, canonical)


def _row_error(
    row: int,
    field: str | None,
    code: str,
    message: str,
    value: Any = None,
) -> RowError:
    text = None
    if value is not None:
        text = str(value).strip()
        if len(text) > 200:
            text = text[:197] + "..."
    return RowError(row=row, field=field, code=code, message=message, value=text)


def _required_error(row: int, field: str) -> RowError:
    return _row_error(
        row,
        field,
        "requerido",
        f"El campo '{field}' es obligatorio.",
    )


def _missing_column_error(row: int, field: str) -> RowError:
    return _row_error(
        row,
        field,
        "columna_faltante",
        f"Falta la columna obligatoria '{field}'.",
    )


def _get_value(raw: Mapping[str, Any], field: str, mapping: Mapping[str, str | None]) -> Any:
    source = mapping.get(field)
    if source is not None:
        if source in raw:
            return raw[source]
        # Soporta listas de diccionarios ya normalizadas aunque el mapping
        # explicito apunte a headers del archivo original.
        if field in raw:
            return raw[field]
        return None
    return raw.get(field)


def _prepare_employee(
    raw: Mapping[str, Any],
    mapping: Mapping[str, str | None],
    row: int,
    missing: set[str],
) -> tuple[EmployeeRow | None, list[RowError]]:
    issues: list[RowError] = []
    data: dict[str, Any] = {}

    raw_legajo = _get_value(raw, "legajo", mapping)
    if is_blank(raw_legajo):
        if "legajo" not in missing:
            issues.append(_required_error(row, "legajo"))
    else:
        legajo = clean_legajo(raw_legajo)
        if legajo is None:
            issues.append(_required_error(row, "legajo"))
        else:
            data["legajo"] = legajo

    for field in ("apellido", "nombre"):
        raw_value = _get_value(raw, field, mapping)
        if is_blank(raw_value):
            if field not in missing:
                issues.append(_required_error(row, field))
            continue
        value = clean_text(raw_value)
        if value is None:
            issues.append(_required_error(row, field))
        else:
            data[field] = value

    raw_cuil = _get_value(raw, "cuil", mapping)
    if is_blank(raw_cuil):
        if "cuil" not in missing:
            issues.append(_required_error(row, "cuil"))
    else:
        cuil = normalize_cuil(raw_cuil)
        if cuil is None or not is_valid_cuil(cuil):
            issues.append(
                _row_error(
                    row,
                    "cuil",
                    "cuil_invalido",
                    "El CUIL no es valido o no coincide su digito verificador.",
                    raw_cuil,
                )
            )
        else:
            data["cuil"] = cuil

    raw_fecha = _get_value(raw, "fecha_ingreso", mapping)
    if is_blank(raw_fecha):
        if "fecha_ingreso" not in missing:
            issues.append(_required_error(row, "fecha_ingreso"))
    else:
        fecha = parse_date(raw_fecha)
        if fecha is None:
            issues.append(
                _row_error(
                    row,
                    "fecha_ingreso",
                    "fecha_invalida",
                    "La fecha de ingreso no es valida.",
                    raw_fecha,
                )
            )
        else:
            data["fecha_ingreso"] = fecha

    for field in ("categoria", "convenio"):
        value = clean_text(_get_value(raw, field, mapping))
        if value is not None:
            data[field] = value

    raw_email = _get_value(raw, "email", mapping)
    if not is_blank(raw_email):
        email = clean_text(raw_email)
        if email is None or not is_valid_email(email):
            issues.append(
                _row_error(
                    row,
                    "email",
                    "email_invalido",
                    "El email no es valido.",
                    raw_email,
                )
            )
        else:
            data["email"] = email

    if missing or issues:
        return None, issues

    try:
        return EmployeeRow(**data), []
    except ValidationError as exc:
        return None, model_validation_errors(exc, row)


def _prepare_novelty(
    raw: Mapping[str, Any],
    mapping: Mapping[str, str | None],
    row: int,
    missing: set[str],
) -> tuple[NoveltyRow | None, list[RowError]]:
    issues: list[RowError] = []
    data: dict[str, Any] = {}

    raw_legajo = _get_value(raw, "legajo", mapping)
    if is_blank(raw_legajo):
        if "legajo" not in missing:
            issues.append(_required_error(row, "legajo"))
    else:
        legajo = clean_legajo(raw_legajo)
        if legajo is None:
            issues.append(_required_error(row, "legajo"))
        else:
            data["legajo"] = legajo

    raw_periodo = _get_value(raw, "periodo", mapping)
    if is_blank(raw_periodo):
        if "periodo" not in missing:
            issues.append(_required_error(row, "periodo"))
    else:
        periodo = parse_periodo(raw_periodo)
        if periodo is None:
            issues.append(
                _row_error(
                    row,
                    "periodo",
                    "periodo_invalido",
                    "El periodo debe tener formato AAAAMM o ser una fecha valida.",
                    raw_periodo,
                )
            )
        else:
            data["periodo"] = periodo

    implied_tipo = implied_type_for_header(mapping.get("tipo"))
    if implied_tipo is not None:
        data["tipo"] = implied_tipo
    else:
        raw_tipo = _get_value(raw, "tipo", mapping)
        if is_blank(raw_tipo):
            if "tipo" not in missing:
                issues.append(_required_error(row, "tipo"))
        else:
            tipo = normalize_tipo(raw_tipo)
            if tipo is None:
                issues.append(
                    _row_error(
                        row,
                        "tipo",
                        "tipo_invalido",
                        "El tipo de novedad no es valido.",
                        raw_tipo,
                    )
                )
            else:
                data["tipo"] = tipo

    raw_cantidad = _get_value(raw, "cantidad", mapping)
    if not is_blank(raw_cantidad):
        cantidad = parse_decimal(raw_cantidad)
        if cantidad is None:
            issues.append(
                _row_error(
                    row,
                    "cantidad",
                    "cantidad_invalida",
                    "La cantidad no es un numero valido.",
                    raw_cantidad,
                )
            )
        else:
            data["cantidad"] = cantidad

    raw_importe = _get_value(raw, "importe", mapping)
    if not is_blank(raw_importe):
        importe = parse_decimal(raw_importe, places=2)
        if importe is None:
            issues.append(
                _row_error(
                    row,
                    "importe",
                    "importe_invalido",
                    "El importe no es un monto valido.",
                    raw_importe,
                )
            )
        else:
            data["importe"] = importe

    observacion = clean_text(_get_value(raw, "observacion", mapping))
    if observacion is not None:
        data["observacion"] = observacion

    if missing or issues:
        return None, issues

    try:
        return NoveltyRow(**data), []
    except ValidationError as exc:
        return None, model_validation_errors(exc, row)


def _duplicate_key(kind: ImportKind, row: RowModel) -> str:
    legajo = str(row["legajo"]).strip().casefold()
    if kind == "employees":
        return f"legajo:{legajo}"
    return f"legajo:{legajo}|periodo:{row['periodo']}|tipo:{row['tipo']}"


def _duplicate_message(kind: ImportKind) -> str:
    if kind == "employees":
        return "Fila duplicada: ya existe una fila valida con el mismo legajo."
    return (
        "Fila duplicada: ya existe una fila valida con el mismo legajo, "
        "periodo y tipo de novedad."
    )


def _analyze_records(
    records: Sequence[tuple[int, Mapping[str, Any]]],
    kind: ImportKind,
    mapping: Mapping[str, str | None],
    missing: list[str],
) -> tuple[int, list[EmployeeRow | NoveltyRow], list[RowError], list[DuplicateRow]]:
    total = len(records)
    valid_rows: list[EmployeeRow | NoveltyRow] = []
    errors: list[RowError] = []
    duplicates: list[DuplicateRow] = []
    seen: dict[str, int] = {}
    missing_set = set(missing)

    if total == 0 and missing:
        for field in missing:
            errors.append(_missing_column_error(1, field))
        return total, valid_rows, errors, duplicates

    for row_number, raw in records:
        row_errors = [_missing_column_error(row_number, field) for field in missing]
        model: EmployeeRow | NoveltyRow | None
        if kind == "employees":
            model, field_errors = _prepare_employee(raw, mapping, row_number, missing_set)
        else:
            model, field_errors = _prepare_novelty(raw, mapping, row_number, missing_set)
        row_errors.extend(field_errors)

        if model is not None and not row_errors:
            key = _duplicate_key(kind, model)
            first_row = seen.get(key)
            if first_row is not None:
                duplicates.append(
                    DuplicateRow(
                        row=row_number,
                        first_row=first_row,
                        key=key,
                        message=_duplicate_message(kind),
                    )
                )
                continue
            seen[key] = row_number
            valid_rows.append(model)
        else:
            if not row_errors:
                row_errors.append(
                    _row_error(
                        row_number,
                        None,
                        "fila_invalida",
                        "La fila no pudo validarse.",
                    )
                )
            errors.extend(row_errors)

    return total, valid_rows, errors, duplicates


def _table_records(table: Table) -> list[tuple[int, dict[str, Any]]]:
    headers = table.headers
    records: list[tuple[int, dict[str, Any]]] = []
    for row_number, values in table.rows:
        raw = dict(zip(headers, values, strict=False))
        if all(is_blank(value) for value in raw.values()):
            continue
        records.append((row_number, raw))
    return records


def analyze_file(
    stream: Any,
    kind: str,
    mapping: Mapping[str, Any] | None = None,
) -> ImportPreview:
    """Analiza un CSV/XLSX y devuelve un preview sin persistir nada.

    ``mapping`` permite indicar columnas propias, por ejemplo
    ``{"legajo": "Nro Legajo", "fecha_ingreso": "Fecha alta"}``. Si se omite,
    se resuelven los encabezados en espanol y sus aliases.
    """
    canonical_kind = normalize_kind(kind)
    table = read_table(stream)
    resolved = resolve_mapping(table.headers, canonical_kind, mapping)
    missing = missing_columns(canonical_kind, resolved)

    if not table.headers or not any(normalize_text(header) for header in table.headers):
        return ImportPreview(
            kind=canonical_kind,
            total=0,
            valid_rows=[],
            errors=[
                RowError(
                    row=0,
                    field=None,
                    code="archivo_vacio",
                    message="El archivo no contiene encabezados ni datos.",
                )
            ],
            duplicates=[],
            dry_run=True,
            mapping=resolved,
            missing_columns=[],
        )

    total, valid_rows, errors, duplicates = _analyze_records(
        _table_records(table), canonical_kind, resolved, missing
    )
    if total == 0 and not errors:
        errors.append(
            RowError(
                row=1,
                field=None,
                code="sin_datos",
                message="El archivo no contiene filas de datos.",
            )
        )
    return ImportPreview(
        kind=canonical_kind,
        total=total,
        valid_rows=valid_rows,
        errors=errors,
        duplicates=duplicates,
        dry_run=True,
        mapping=resolved,
        missing_columns=missing,
    )


def _coerce_records(
    rows: Iterable[Mapping[str, Any] | RowModel] | Mapping[str, Any] | RowModel,
) -> list[tuple[int, dict[str, Any]]]:
    if rows is None:
        return []
    if isinstance(rows, Mapping) or isinstance(rows, RowModel):
        iterable: Iterable[Any] = [rows]
    else:
        iterable = rows

    records: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(iterable):
        row_number = index + 2
        if isinstance(row, RowModel):
            raw = row.model_dump()
        elif isinstance(row, Mapping):
            raw = dict(row)
        else:
            raise TypeError(
                "Cada fila debe ser un diccionario o un modelo de importacion."
            )

        for key in ("__row__", "_row", "fila"):
            if key in raw:
                candidate = raw.pop(key)
                if isinstance(candidate, int) and candidate > 0:
                    row_number = candidate
                break

        if not raw or all(is_blank(value) for value in raw.values()):
            continue
        records.append((row_number, raw))
    return records


def import_rows(
    rows: Iterable[Mapping[str, Any] | RowModel] | Mapping[str, Any] | RowModel,
    kind: str,
    mapping: Mapping[str, Any] | None = None,
) -> ImportResult:
    """Revalida filas ya extraidas. La operacion es pura y siempre dry-run.

    Acepta diccionarios con headers originales o campos canonicos, y tambien
    los modelos devueltos en ``ImportPreview.valid_rows``. No persiste datos:
    el resultado solo informa ``valid_rows``, ``errors`` y ``duplicates``.
    """
    canonical_kind = normalize_kind(kind)
    records = _coerce_records(rows)
    headers: list[str] = []
    for _, raw in records:
        for key in raw:
            text = str(key)
            if text not in headers:
                headers.append(text)
    resolved = resolve_mapping(headers, canonical_kind, mapping)
    total, valid_rows, errors, duplicates = _analyze_records(
        records, canonical_kind, resolved, []
    )
    return ImportResult(
        kind=canonical_kind,
        total=total,
        valid_rows=valid_rows,
        errors=errors,
        duplicates=duplicates,
        dry_run=True,
    )


__all__ = ["analyze_file", "import_rows", "normalize_kind"]
