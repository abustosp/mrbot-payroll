"""Resolucion de headers en espanol hacia los campos canonicos.

Los archivos reales suelen traer encabezados como ``Legajo``, ``Apellido``,
``CUIL``, ``Fecha de ingreso`` o ``Horas extra``. La comparacion normaliza
acentos, mayusculas, guiones y espacios para que ``"Período"`` y ``"PERIODO"``
sean equivalentes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.importers.parsing import normalize_text

EMPLOYEE_FIELDS = (
    "legajo",
    "apellido",
    "nombre",
    "cuil",
    "fecha_ingreso",
    "categoria",
    "convenio",
    "email",
)
NOVELTY_FIELDS = (
    "legajo",
    "periodo",
    "tipo",
    "cantidad",
    "importe",
    "observacion",
    "naturaleza",
    "quincena",
)

CONCEPT_FIELDS = (
    "codigo",
    "nombre",
    "naturaleza",
    "descripcion",
)

REQUIRED_FIELDS = {
    "employees": ("legajo", "apellido", "nombre", "cuil", "fecha_ingreso"),
    "novelties": ("legajo", "periodo", "tipo"),
    "concepts": ("codigo", "nombre"),
}

_CONCEPT_ALIASES = {
    "codigo": (
        "codigo",
        "cod",
        "code",
        "codigo concepto",
        "codigo de concepto",
        "cod concepto",
    ),
    "nombre": (
        "nombre",
        "descripcion concepto",
        "concepto",
        "name",
        "denominacion",
    ),
    "naturaleza": (
        "naturaleza",
        "tipo",
        "kind",
        "nature",
        "naturaleza concepto",
    ),
    "descripcion": (
        "descripcion",
        "description",
        "detalle",
        "observacion",
    ),
}

_EMPLOYEE_ALIASES = {
    "legajo": (
        "legajo",
        "legajos",
        "nro legajo",
        "nro de legajo",
        "numero legajo",
        "numero de legajo",
        "n legajo",
        "legajo empleado",
        "legajo del empleado",
        "codigo empleado",
        "codigo de empleado",
        "cod empleado",
        "id empleado",
    ),
    "apellido": (
        "apellido",
        "apellidos",
        "apellido empleado",
        "apellido del empleado",
    ),
    "nombre": (
        "nombre",
        "nombres",
        "nombre empleado",
        "nombre del empleado",
    ),
    "cuil": (
        "cuil",
        "cuit",
        "cuil empleado",
        "cuit empleado",
        "cuil trabajador",
        "cuit trabajador",
        "cuil cuit",
    ),
    "fecha_ingreso": (
        "fecha de ingreso",
        "fecha ingreso",
        "fecha de alta",
        "fecha alta",
        "alta",
        "ingreso",
        "fecha inicio",
        "fecha de inicio",
    ),
    "categoria": (
        "categoria",
        "categoria laboral",
        "categoria empleado",
        "puesto",
        "funcion",
    ),
    "convenio": (
        "convenio",
        "cct",
        "convenio colectivo",
        "convenio cct",
        "cct aplicable",
    ),
    "email": (
        "email",
        "e mail",
        "mail",
        "correo",
        "correo electronico",
        "correo electronico laboral",
    ),
}

_NOVELTY_ALIASES = {
    "legajo": _EMPLOYEE_ALIASES["legajo"],
    "periodo": (
        "periodo",
        "periodo liquidacion",
        "periodo de liquidacion",
        "periodo imputado",
        "mes",
        "mes liquidacion",
        "mes de liquidacion",
        "competencia",
    ),
    "tipo": (
        "tipo",
        "tipo novedad",
        "tipo de novedad",
        "novedad",
        "concepto",
        "concepto novedad",
        "codigo concepto",
    ),
    "cantidad": (
        "cantidad",
        "cant",
        "cantidades",
        "unidades",
        "horas",
        "dias",
        "dias trabajados",
    ),
    "importe": (
        "importe",
        "monto",
        "valor",
        "importe novedad",
        "total",
        "importe total",
    ),
    "observacion": (
        "observacion",
        "observaciones",
        "detalle",
        "comentario",
        "comentarios",
        "descripcion",
        "nota",
    ),
    "naturaleza": (
        "naturaleza",
        "naturaleza novedad",
        "caracter",
        "caracter novedad",
        "kind",
        "tipo naturaleza",
        "remunerativo",
    ),
    "quincena": (
        "quincena",
        "subperiodo",
        "subperiodo quincena",
        "q",
        "dia",
        "dia quincena",
    ),
}

# Columnas que, ademas de contener un valor, identifican el tipo de novedad.
# Ejemplo: una planilla con la columna "Horas extra" implica tipo horas_extra y
# cantidad tomada de esa misma columna.
_TYPE_HEADERS: dict[str, tuple[str, str]] = {
    "horas extra": ("horas_extra", "cantidad"),
    "horas extras": ("horas_extra", "cantidad"),
    "hora extra": ("horas_extra", "cantidad"),
    "ausencia": ("ausencia", "cantidad"),
    "ausencias": ("ausencia", "cantidad"),
    "dias de ausencia": ("ausencia", "cantidad"),
    "vacaciones": ("vacaciones", "cantidad"),
    "dias de vacaciones": ("vacaciones", "cantidad"),
    "licencia": ("licencia", "cantidad"),
    "licencias": ("licencia", "cantidad"),
    "dias de licencia": ("licencia", "cantidad"),
    "adelanto": ("adelanto", "importe"),
    "adelantos": ("adelanto", "importe"),
    "comision": ("comision", "importe"),
    "comisiones": ("comision", "importe"),
    "bonificacion": ("bonificacion", "importe"),
    "bonificaciones": ("bonificacion", "importe"),
    "embargo": ("embargo", "importe"),
    "embargos": ("embargo", "importe"),
}
_TYPE_HEADERS_COMPACT = {key.replace(" ", ""): value for key, value in _TYPE_HEADERS.items()}

_ALIASES = {
    "employees": _EMPLOYEE_ALIASES,
    "novelties": _NOVELTY_ALIASES,
    "concepts": _CONCEPT_ALIASES,
}
_FIELDS = {
    "employees": EMPLOYEE_FIELDS,
    "novelties": NOVELTY_FIELDS,
    "concepts": CONCEPT_FIELDS,
}


def fields_for(kind: str) -> tuple[str, ...]:
    return _FIELDS[kind]


def required_fields_for(kind: str) -> tuple[str, ...]:
    return REQUIRED_FIELDS[kind]


def implied_type_for_header(header: Any) -> str | None:
    """Devuelve el tipo implicito de una columna como ``Horas extra``."""
    if header is None:
        return None
    normalized = normalize_text(header)
    value = _TYPE_HEADERS.get(normalized) or _TYPE_HEADERS_COMPACT.get(
        normalized.replace(" ", "")
    )
    return value[0] if value else None


def _normalized_headers(headers: list[Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers:
        if header is None:
            continue
        text = str(header).strip()
        normalized = normalize_text(text)
        if not normalized:
            continue
        if normalized not in result:
            result[normalized] = text
        compact = normalized.replace(" ", "")
        if compact not in result:
            result[compact] = text
    return result


def _lookup_header(available: Mapping[str, str], source: Any) -> str | None:
    normalized = normalize_text(source)
    if not normalized:
        return None
    return available.get(normalized) or available.get(normalized.replace(" ", ""))


def _explicit_mapping(
    mapping: Mapping[str, Any] | None, fields: tuple[str, ...]
) -> dict[str, str]:
    """Acepta tanto ``{campo: header}`` como ``{header: campo}``."""
    if not mapping:
        return {}
    normalized_fields = {normalize_text(field): field for field in fields}
    explicit: dict[str, str] = {}
    for key, value in mapping.items():
        normalized_key = normalize_text(key)
        normalized_value = normalize_text(value)
        if normalized_key in normalized_fields:
            explicit[normalized_fields[normalized_key]] = str(value)
        elif normalized_value in normalized_fields:
            explicit[normalized_fields[normalized_value]] = str(key)
    return explicit


def resolve_mapping(
    headers: list[Any],
    kind: str,
    mapping: Mapping[str, Any] | None = None,
) -> dict[str, str | None]:
    """Devuelve ``campo canonico -> header original`` para un archivo.

    ``mapping`` explicito tiene prioridad. Si no alcanza, se resuelven los
    aliases conocidos. Los campos no encontrados quedan en ``None``.
    """
    fields = fields_for(kind)
    available = _normalized_headers(headers)
    resolved: dict[str, str | None] = {field: None for field in fields}

    for field, source in _explicit_mapping(mapping, fields).items():
        actual = _lookup_header(available, source)
        if actual is not None:
            resolved[field] = actual

    aliases = _ALIASES[kind]
    for field in fields:
        if resolved[field] is not None:
            continue
        for alias in aliases[field]:
            actual = _lookup_header(available, alias)
            if actual is not None:
                resolved[field] = actual
                break

    if kind == "novelties":
        # Si no hay columna "Tipo" pero si una columna especifica ("Horas
        # extra", "Adelantos", etc.), esa columna identifica el tipo.
        if resolved["tipo"] is None:
            for normalized, (_, _) in _TYPE_HEADERS.items():
                actual = _lookup_header(available, normalized)
                if actual is not None:
                    resolved["tipo"] = actual
                    break
        if resolved["tipo"] is not None:
            type_key = normalize_text(resolved["tipo"])
            type_field, value_field = _TYPE_HEADERS.get(
                type_key,
                _TYPE_HEADERS_COMPACT.get(type_key.replace(" ", ""), (None, None)),
            )
            if type_field and value_field is not None and resolved[value_field] is None:
                resolved[value_field] = resolved["tipo"]

    return resolved


def missing_columns(kind: str, mapping: Mapping[str, str | None]) -> list[str]:
    """Lista los campos obligatorios que no tienen columna de origen."""
    return [field for field in required_fields_for(kind) if not mapping.get(field)]
