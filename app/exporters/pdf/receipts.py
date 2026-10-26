"""Render de recibos de sueldo a HTML, PDF y ZIP.

Este modulo es exclusivamente de presentacion: no calcula reglas de negocio ni
importes. Los totales y conceptos deben llegar ya calculados por el motor de
liquidacion o por el servicio que lo invoque.

Contrato de contexto (claves canonicas)::

    {
        "receipt_number": "R-2026-09-0001",
        "issue_date": date(2026, 9, 30),
        "period": "Septiembre 2026",
        "employer": {
            "name": "Andes Logistica S.A.",
            "cuit": "30-71234567-8",
            "address": "Av. Colon 1234, Cordoba",
            "activity": "Transporte y logistica",
        },
        "employee": {
            "name": "Maria Fernanda Gomez",
            "cuil": "27-30111222-4",
            "file_number": "A-001",
            "category": "Administrativa A",
            "hire_date": date(2018, 3, 12),
            "agreement": "CCT 130/75",
        },
        "items": [
            {"code": "SUELDO_BASICO", "name": "Sueldo basico",
             "kind": "remunerative", "quantity": 1, "unit": "mes",
             "amount": "1850000.00"},
            ...
        ],
        "remunerative_total": "2127500.00",
        "non_remunerative_total": "75000.00",
        "deductions_total": "454850.00",
        "contributions_total": "579387.50",
        "net": "1747650.00",
        "legend": "Texto adicional...",
        "employer_note": "Contribuciones a cargo del empleador...",
    }

Se aceptan alias en espanol para facilitar la integracion
(``empleador``/``trabajador``/``conceptos``/``neto`` y equivalentes). Las
claves desconocidas se ignoran deliberadamente: nunca se vuelca el contexto
completo en el documento, de modo que un secreto o dato interno no puede
filtrarse por accidente.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_NAME = "receipt.html"

KIND_LABELS = {
    "remunerative": "Remunerativo",
    "non_remunerative": "No remunerativo",
    "deduction": "Descuento",
    "contribution": "Contribucion",
}

_KIND_ALIASES = {
    "remunerative": "remunerative",
    "remunerativo": "remunerative",
    "remunerativa": "remunerative",
    "earning": "remunerative",
    "haber": "remunerative",
    "non_remunerative": "non_remunerative",
    "non-remunerative": "non_remunerative",
    "no_remunerative": "non_remunerative",
    "no_remunerativo": "non_remunerative",
    "no_remunerativa": "non_remunerative",
    "non_remunerativo": "non_remunerative",
    "deduction": "deduction",
    "descuento": "deduction",
    "descuentos": "deduction",
    "contribution": "contribution",
    "contribucion": "contribution",
    "contribuciones": "contribution",
    "employer_contribution": "contribution",
}

_DEFAULT_LEGEND = (
    "Recibo de sueldo emitido conforme al artículo 140 de la Ley de Contrato "
    "de Trabajo. La emisión de este PDF no acredita por sí sola la firma, "
    "entrega o conservación electrónica del recibo."
)
_DEFAULT_EMPLOYER_NOTE = (
    "Contribuciones y aportes a cargo del empleador informados a título "
    "ilustrativo. Los importes definitivos surgen de la declaración jurada "
    "y de los parámetros vigentes del período."
)


class ReceiptError(ValueError):
    """Error de datos o de render del recibo."""


class ReceiptContextError(ReceiptError):
    """El contexto no contiene los datos minimos del recibo."""


class PdfRendererUnavailable(RuntimeError):
    """WeasyPrint no esta disponible en el entorno de ejecucion."""


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(source: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def _to_decimal(value: Any, field: str = "importe") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        raise ReceiptContextError(f"Falta el {field}.")
    if isinstance(value, bool):
        raise ReceiptContextError(f"El {field} no es un numero valido.")
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ReceiptContextError(f"El {field} no es un numero valido: {value!r}.") from exc


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return _to_decimal(value)


def _format_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    raw = _text(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw


def _format_money(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        amount = _to_decimal(value)
    except ReceiptContextError:
        return _text(value)
    negative = amount < 0
    amount = abs(amount)
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if negative else ''}$ {formatted}"


def _format_quantity(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        amount = _to_decimal(value, "cantidad")
    except ReceiptContextError:
        return _text(value)
    if amount == amount.to_integral_value():
        return f"{amount:,.0f}".replace(",", ".")
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@lru_cache(maxsize=1)
def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html", "htm", "xml"), default=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["money"] = _format_money
    env.filters["quantity"] = _format_quantity
    env.filters["date_ar"] = _format_date
    env.globals["kind_label"] = lambda kind: KIND_LABELS.get(kind, kind)
    return env


def _normalize_employer(raw: Any) -> dict[str, str]:
    raw = {"name": raw} if isinstance(raw, str) else _mapping(raw)
    return {
        "name": _text(
            _first(
                raw,
                "name",
                "razon_social",
                "legal_name",
                "nombre",
                "company_name",
                "business_name",
            )
        ),
        "cuit": _text(_first(raw, "cuit", "tax_id", "cuit_empleador")),
        "address": _text(_first(raw, "address", "domicilio", "direccion")),
        "activity": _text(_first(raw, "activity", "actividad")),
        "establishment": _text(_first(raw, "establishment", "establecimiento")),
    }


def _normalize_employee(raw: Any) -> dict[str, str]:
    raw = {"name": raw} if isinstance(raw, str) else _mapping(raw)
    name = _text(
        _first(raw, "name", "nombre", "full_name", "nombre_completo", "employee_name")
    )
    if not name:
        first_name = _text(_first(raw, "first_name", "nombres"))
        last_name = _text(_first(raw, "last_name", "apellido", "apellidos"))
        name = " ".join(part for part in (first_name, last_name) if part)
    return {
        "name": name,
        "cuil": _text(_first(raw, "cuil", "tax_id", "cuil_trabajador")),
        "file_number": _text(_first(raw, "file_number", "legajo", "numero_legajo")),
        "category": _text(_first(raw, "category", "categoria", "categoria_profesional")),
        "hire_date": _format_date(_first(raw, "hire_date", "fecha_ingreso", "start_date")),
        "agreement": _text(_first(raw, "agreement", "convenio", "cct")),
        "document": _text(_first(raw, "document", "dni", "documento")),
    }


def _normalize_items(raw_items: Any) -> list[dict[str, Any]]:
    if raw_items is None:
        return []
    if isinstance(raw_items, Mapping):
        raw_items = [raw_items]
    if not isinstance(raw_items, Iterable) or isinstance(raw_items, (str, bytes)):
        raise ReceiptContextError("El campo items debe ser una lista de conceptos.")

    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items, 1):
        item = _mapping(raw)
        kind_raw = _text(
            _first(item, "kind", "tipo", "type", "nature", "naturaleza")
        ).casefold()
        kind = _KIND_ALIASES.get(kind_raw)
        if kind is None:
            raise ReceiptContextError(
                f"Concepto #{index}: tipo desconocido {kind_raw!r}. "
                "Use remunerative, non_remunerative, deduction o contribution."
            )
        name = _text(
            _first(
                item,
                "name",
                "nombre",
                "description",
                "descripcion",
                "concept_name",
            )
        )
        if not name:
            raise ReceiptContextError(f"Concepto #{index}: falta el nombre.")
        items.append(
            {
                "code": _text(_first(item, "code", "codigo")),
                "name": name,
                "kind": kind,
                "kind_label": KIND_LABELS[kind],
                "quantity": _first(item, "quantity", "cantidad"),
                "unit": _text(_first(item, "unit", "unidad")),
                "amount": _to_decimal(
                    _first(item, "amount", "importe", "value", "valor", "total"),
                    f"importe del concepto {name!r}",
                ),
            }
        )
    return items


def _normalize_context(context: Mapping[str, Any] | Any) -> dict[str, Any]:
    source = _mapping(context)
    if not source:
        raise ReceiptContextError("El contexto del recibo esta vacio.")

    employer = _normalize_employer(_first(source, "employer", "empleador"))
    employee = _normalize_employee(_first(source, "employee", "trabajador", "worker"))
    items = _normalize_items(_first(source, "items", "conceptos", "concepts"))

    errors: list[str] = []
    if not employer["name"]:
        errors.append("employer.name")
    if not employee["name"]:
        errors.append("employee.name")
    receipt_number = (
        _text(_first(source, "receipt_number", "numero_recibo", "number")) or "S/N"
    )
    period = _text(_first(source, "period", "periodo", "period_label"))
    if not period:
        errors.append("period")
    if not items:
        errors.append("items")
    if errors:
        raise ReceiptContextError("Faltan datos obligatorios del recibo: " + ", ".join(errors) + ".")

    grouped: dict[str, list[dict[str, Any]]] = {
        "remunerative": [],
        "non_remunerative": [],
        "deduction": [],
        "contribution": [],
    }
    for item in items:
        grouped[item["kind"]].append(item)

    totals: dict[str, Decimal] = {}
    total_fields = {
        "remunerative": ("remunerative_total", "total_remunerativo", "remunerativo"),
        "non_remunerative": (
            "non_remunerative_total",
            "total_no_remunerativo",
            "no_remunerativo",
        ),
        "deduction": ("deductions_total", "total_descuentos", "descuentos"),
        "contribution": (
            "contributions_total",
            "total_contribuciones",
            "contribuciones",
        ),
    }
    for kind, aliases in total_fields.items():
        explicit = _optional_decimal(_first(source, *aliases))
        totals[kind] = explicit if explicit is not None else sum(
            (item["amount"] for item in grouped[kind]), Decimal("0.00")
        )

    net_raw = _first(source, "net", "neto", "net_amount", "importe_neto")
    net = _to_decimal(net_raw, "neto")

    issue_date = _format_date(_first(source, "issue_date", "fecha_emision", "fecha"))
    period_start = _format_date(_first(source, "period_start", "periodo_desde"))
    period_end = _format_date(_first(source, "period_end", "periodo_hasta"))

    return {
        "receipt_number": receipt_number,
        "issue_date": issue_date,
        "period": period,
        "period_start": period_start,
        "period_end": period_end,
        "employer": employer,
        "employee": employee,
        "items": items,
        "groups": [
            {
                "key": "remunerative",
                "label": "Haberes remunerativos",
                "items": grouped["remunerative"],
                "subtotal": totals["remunerative"],
            },
            {
                "key": "non_remunerative",
                "label": "Haberes no remunerativos",
                "items": grouped["non_remunerative"],
                "subtotal": totals["non_remunerative"],
            },
        ],
        "deductions": grouped["deduction"],
        "contributions": grouped["contribution"],
        "remunerative_total": totals["remunerative"],
        "non_remunerative_total": totals["non_remunerative"],
        "deductions_total": totals["deduction"],
        "contributions_total": totals["contribution"],
        "gross_total": totals["remunerative"] + totals["non_remunerative"],
        "net": net,
        "legend": _text(_first(source, "legend", "leyenda"), _DEFAULT_LEGEND),
        "employer_note": _text(
            _first(source, "employer_note", "nota_empleador"), _DEFAULT_EMPLOYER_NOTE
        ),
    }


def render_receipt_html(context: Mapping[str, Any] | Any) -> str:
    """Renderiza el recibo como HTML autonomo (CSS incluido).

    Todos los datos provistos por el usuario se escapan mediante autoescape de
    Jinja2. El contexto se normaliza a una lista blanca de campos.
    """

    view = _normalize_context(context)
    template = _environment().get_template(TEMPLATE_NAME)
    return template.render(receipt=view)


def _load_weasyprint_html():
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - depende del entorno del sistema
        raise PdfRendererUnavailable(
            "WeasyPrint no esta disponible. Instale las dependencias del sistema "
            "requeridas por WeasyPrint o utilice render_receipt_html()."
        ) from exc
    return HTML


def render_receipt_pdf(context: Mapping[str, Any] | Any) -> bytes:
    """Renderiza un unico recibo a PDF usando WeasyPrint."""

    html = render_receipt_html(context)
    html_class = _load_weasyprint_html()
    try:
        return html_class(string=html, base_url=str(TEMPLATE_DIR)).write_pdf()
    except Exception as exc:
        raise ReceiptError("No se pudo generar el PDF del recibo.") from exc


def _safe_filename(context: Mapping[str, Any], index: int) -> str:
    raw = _text(_first(_mapping(context), "receipt_number", "numero_recibo", "number"))
    if not raw:
        raw = f"recibo-{index:04d}"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("._-")
    stem = stem[:80] or f"recibo-{index:04d}"
    if not stem.lower().endswith(".pdf"):
        stem += ".pdf"
    return stem


def render_receipts_zip(contexts: Iterable[Mapping[str, Any]]) -> bytes:
    """Genera un ZIP con un PDF por recibo.

    Los nombres se derivan del numero de recibo, se sanean y se desduplican.
    No se incluyen datos personales en los nombres de archivo.
    """

    items = list(contexts)
    if not items:
        raise ReceiptContextError("Se requiere al menos un recibo para generar el ZIP.")

    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, context in enumerate(items, 1):
            filename = _safe_filename(context, index)
            candidate = filename
            counter = 2
            while candidate.casefold() in used:
                candidate = f"{filename[:-4]}-{counter}.pdf"
                counter += 1
            used.add(candidate.casefold())
            archive.writestr(candidate, render_receipt_pdf(context))
    return buffer.getvalue()


@lru_cache(maxsize=1)
def pdf_backend_status() -> tuple[bool, str]:
    """Devuelve disponibilidad y version de WeasyPrint sin importarlo."""

    if find_spec("weasyprint") is None:
        return False, "WeasyPrint no instalado"
    try:
        installed = version("weasyprint")
    except PackageNotFoundError:
        installed = "desconocida"
    return True, f"WeasyPrint {installed}"


__all__ = [
    "KIND_LABELS",
    "PdfRendererUnavailable",
    "ReceiptContextError",
    "ReceiptError",
    "pdf_backend_status",
    "render_receipt_html",
    "render_receipt_pdf",
    "render_receipts_zip",
]
