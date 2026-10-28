"""Fixed-width Libro de Sueldos Digital serializer.

Layouts mirror the official AFIP build tools for "Libro de Sueldos Digital"
(Herramientas de trabajo: LSD-ARMADO-TXT-Liquidaciones.xlsx and
LSD-ARMADO-TXT-Conceptos.xlsx, sheet "Interfase"): 01 (35), 02 (115),
03 (51), 04 (370), 05 (65), 06 (93) and conceptos (195, no record-type
prefix). Lines are ASCII, encoded as Latin-1 with CRLF separators.

The output is a draft for internal validation; it does not claim ARCA
acceptance and does not replace the official validations. The generator only
emits "SJ" shipments, so reg-01 "Días base" is always numeric (the blank form
is reserved for "RE" rectification-only files, which are not generated here).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.jurisdictions.argentina.validation import normalize_cuit_cuil, validate_period

ENCODING = "latin-1"
LAYOUT_VERSION = "afip-2025.09"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    width: int
    kind: str = "text"
    align: str = "left"
    fill: str = " "
    required: bool = False
    decimals: int = 2

    def __post_init__(self) -> None:
        if not self.name or self.width < 1:
            raise ValueError("field name and positive width are required")
        if self.kind not in {"text", "integer", "amount", "date", "period", "cuit", "cuil", "flag"}:
            raise ValueError(f"Tipo de campo no soportado: {self.kind}")
        if self.align not in {"left", "right"}:
            raise ValueError("align must be 'left' or 'right'")
        if len(self.fill) != 1 or not self.fill.isascii():
            raise ValueError("fill must be one ASCII character")
        if self.decimals < 0:
            raise ValueError("decimals cannot be negative")


@dataclass(frozen=True, slots=True)
class RecordLayout:
    record_type: str
    fields: tuple[FieldSpec, ...]
    length: int
    version: str = LAYOUT_VERSION

    def __post_init__(self) -> None:
        if sum(item.width for item in self.fields) != self.length:
            raise ValueError(f"layout {self.record_type} fields do not total {self.length}")
        names = [item.name for item in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"layout {self.record_type} has duplicate field names")


def _field(
    name: str,
    width: int,
    kind: str = "text",
    *,
    align: str | None = None,
    fill: str | None = None,
    required: bool = False,
    decimals: int = 2,
) -> FieldSpec:
    numeric = kind in {"integer", "amount", "period", "cuit", "cuil"}
    return FieldSpec(
        name=name,
        width=width,
        kind=kind,
        align=align or ("right" if numeric else "left"),
        fill=fill if fill is not None else ("0" if numeric else " "),
        required=required,
        decimals=decimals,
    )


_RECORDS: dict[str, RecordLayout] = {
    "01": RecordLayout("01", (
        _field("record_type", 2, required=True),
        _field("cuit", 11, "cuit", required=True),
        _field("send_id", 2),
        _field("period", 6, "period", required=True),
        _field("liquidation_type", 1),
        _field("liquidation_number", 5, "integer"),
        _field("base_days", 2, "integer"),
        _field("worker_count", 6, "integer", required=True),
    ), 35),
    "02": RecordLayout("02", (
        _field("record_type", 2, required=True),
        _field("cuil", 11, "cuil", required=True),
        _field("employee_id", 10),
        _field("branch", 50),
        # Official tool right-aligns CBU with spaces; rubric date is
        # space-padded (not zero-padded) when present.
        _field("bank_account", 22, align="right", fill=" "),
        _field("days", 3, "integer"),
        # The official tool zero-pads an empty pay date; rubric date is
        # space-padded instead.
        _field("pay_date", 8, "date", fill="0"),
        _field("rubric_date", 8, "date"),
        _field("payment_method", 1, align="right", fill="0"),
    ), 115),
    "03": RecordLayout("03", (
        _field("record_type", 2, required=True),
        _field("cuil", 11, "cuil", required=True),
        _field("concept_code", 10, required=True),
        _field("quantity", 5, "amount"),
        _field("unit", 1),
        _field("amount", 15, "amount", required=True),
        _field("debit_credit", 1),
        # Blank adjustment period renders as spaces in the official tool.
        _field("adjustment_period", 6, "period", fill=" "),
    ), 51),
    "04": RecordLayout("04", (
        _field("record_type", 2, required=True), _field("cuil", 11, "cuil", required=True),
        # Single-char numeric flags are zero-padded in the official tool.
        _field("spouse", 1, align="right", fill="0"),
        _field("children", 2, "integer"), _field("agreement", 1, align="right", fill="0"),
        _field("life_insurance", 1, align="right", fill="0"),
        _field("reduction", 1, align="right", fill="0"),
        _field("employer_type", 1, align="right", fill="0"),
        _field("operation_type", 1, align="right", fill="0"),
        _field("employment_status", 2, align="right", fill="0"),
        _field("condition", 2),
        # condition/contract_mode/disability are left-aligned space-padded in
        # the official tool; activity/locality/health_plan are zero-padded.
        _field("activity", 3, align="right", fill="0"), _field("contract_mode", 3),
        _field("disability", 2),
        _field("locality", 2, align="right", fill="0"),
        # Situation codes and start days are zero-padded numerics.
        _field("situation_1", 2, "integer"), _field("start_day_1", 2, "integer"),
        _field("situation_2", 2, "integer"), _field("start_day_2", 2, "integer"),
        _field("situation_3", 2, "integer"), _field("start_day_3", 2, "integer"),
        _field("worked_days", 2, "integer"), _field("worked_hours", 3, "integer"),
        _field("additional_contribution_rate", 5, "amount"),
        _field("differential_task_rate", 5, "amount"),
        _field("health_plan", 6, align="right", fill="0"),
        _field("dependents", 2, "integer"), _field("additional_health_contribution", 15, "amount"),
        _field("additional_health_employer", 15, "amount"),
        _field("differential_health_base_employee", 15, "amount"),
        _field("differential_health_base_employer", 15, "amount"),
        _field("differential_work_risk_base", 15, "amount"),
        _field("maternity_remuneration", 15, "amount"), _field("gross_remuneration", 15, "amount"),
        *(_field(f"taxable_base_{number}", 15, "amount") for number in range(1, 10)),
        _field("differential_social_security_employee", 15, "amount"),
        _field("differential_social_security_employer", 15, "amount"),
        _field("taxable_base_10", 15, "amount"), _field("deduction_amount", 15, "amount"),
    ), 370),
    # Record 05 "Trabajadores Eventuales": categoria (Simplificacion Registral),
    # puesto, fechas del periodo trabajado, remuneracion (= REM 9 del reg 04)
    # y CUIT del empleador eventual. Dates render zero-padded when empty.
    "05": RecordLayout("05", (
        _field("record_type", 2, required=True), _field("cuil", 11, "cuil", required=True),
        _field("category", 6, align="right", fill="0"),
        _field("position", 4, align="right", fill="0"),
        _field("start_date", 8, "date", fill="0"),
        _field("end_date", 8, "date", fill="0"),
        _field("amount", 15, "amount"),
        _field("employer_cuit", 11, "cuit"),
    ), 65),
    # Record 06 "Observaciones": fixed 93 positions, no period field; the
    # official tool left-pads the free text with zeros.
    "06": RecordLayout("06", (
        _field("record_type", 2, required=True), _field("cuil", 11, "cuil", required=True),
        _field("observation", 80, align="right", fill="0"),
    ), 93),
    # Concept master (Interfase sheet): 6-char ARCA code, 10-char employer
    # code, 150-char description, repeat flag, subsystem flags in fixed
    # positions with reserved blanks, no record-type prefix.
    "concept": RecordLayout("concept", (
        _field("arca_code", 6, required=True),
        _field("employer_code", 10, required=True),
        _field("description", 150, required=True),
        _field("repeat_flag", 1, "flag"),
        _field("sipa_ap", 1, "flag"), _field("sipa_contrib", 1, "flag"),
        _field("inssjyp_ap", 1, "flag"), _field("inssjyp_contrib", 1, "flag"),
        _field("os_ap", 1, "flag"), _field("os_contrib", 1, "flag"),
        _field("fsr_ap", 1, "flag"), _field("fsr_contrib", 1, "flag"),
        _field("renatea_ap", 1, "flag"), _field("renatea_contrib", 1, "flag"),
        _field("reserved_178", 1),
        _field("aaff_contrib", 1, "flag"),
        _field("reserved_180", 1),
        _field("fne_contrib", 1, "flag"),
        _field("reserved_182", 1),
        _field("lrt_contrib", 1, "flag"),
        _field("dif_ap", 1, "flag"),
        _field("reserved_185", 1),
        _field("esp_ap", 1, "flag"),
        _field("reserved_187_195", 9),
    ), 195),
}

LAYOUT_VERSIONS: dict[str, dict[str, RecordLayout]] = {LAYOUT_VERSION: _RECORDS}
RECORD_LENGTHS = {key: layout.length for key, layout in _RECORDS.items()}


def _get_layout(record_type: str, version: str, layouts: Mapping[str, RecordLayout] | None) -> RecordLayout:
    if layouts is not None:
        try:
            return layouts[record_type]
        except KeyError:
            raise ValueError(f"No layout for record {record_type!r}") from None
    try:
        return LAYOUT_VERSIONS[version][record_type]
    except KeyError:
        raise ValueError(f"Unknown LSD layout {version!r} or record {record_type!r}") from None


def _format_date(value: Any, name: str) -> str:
    if isinstance(value, (date, datetime)):
        normalized = value.strftime("%Y%m%d")
    else:
        raw = str(value)
        normalized = raw.replace("-", "") if len(raw) == 10 and raw[4:5] == "-" else raw
    if len(normalized) != 8 or not normalized.isascii() or not normalized.isdigit():
        raise ValueError(f"{name}: se requiere fecha AAAAMMDD o AAAA-MM-DD.")
    try:
        datetime.strptime(normalized, "%Y%m%d")
    except ValueError:
        raise ValueError(f"{name}: fecha inválida.") from None
    return normalized


def _format_field(field: FieldSpec, value: Any) -> str:
    if value is None or value == "":
        if field.required:
            raise ValueError(f"{field.name}: campo obligatorio.")
        return field.fill * field.width
    if field.kind in {"cuit", "cuil"}:
        value = normalize_cuit_cuil(value)
    elif field.kind == "period":
        value = validate_period(value)
    elif field.kind == "date":
        value = _format_date(value, field.name)
    elif field.kind == "integer":
        value = str(value)
        if not value.isascii() or not value.isdigit():
            raise ValueError(f"{field.name}: se requiere un entero no negativo.")
    elif field.kind == "amount":
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError(f"{field.name}: importe inválido.") from None
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"{field.name}: se requiere un importe finito no negativo.")
        scale = Decimal(10) ** field.decimals
        value = str(int((amount * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    else:
        value = str(value)
        if field.kind == "flag" and value not in {"0", "1"}:
            raise ValueError(f"{field.name}: el indicador debe ser 0 o 1.")
    if not value.isascii():
        raise ValueError(f"{field.name}: solo se permite ASCII.")
    if len(value) > field.width:
        raise ValueError(f"{field.name}: supera el máximo de {field.width} caracteres.")
    return value.ljust(field.width, field.fill) if field.align == "left" else value.rjust(field.width, field.fill)


def render_record(
    record_type: str,
    values: Mapping[str, Any],
    *,
    layout_version: str = LAYOUT_VERSION,
    layouts: Mapping[str, RecordLayout] | None = None,
) -> str:
    layout = _get_layout(record_type, layout_version, layouts)
    data = dict(values)
    accepted = {field.name for field in layout.fields}
    if "record_type" in accepted:
        data.setdefault("record_type", record_type)
        if str(data["record_type"]) != record_type:
            raise ValueError(f"record_type no coincide con el layout {record_type}.")
    # Layouts without a record_type field (e.g. "concept") carry no prefix;
    # a record_type key there is rejected as unknown below.
    unknown = set(data) - accepted
    if unknown:
        raise ValueError(f"Campos no definidos en layout {record_type}: {', '.join(sorted(unknown))}")
    line = "".join(_format_field(field, data.get(field.name)) for field in layout.fields)
    if len(line) != layout.length:
        raise ValueError(f"Registro {record_type}: longitud {len(line)}, se esperaba {layout.length}.")
    if not line.isascii():
        raise ValueError("El registro contiene caracteres fuera de ASCII.")
    return line


def _record_parts(record: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    record_type = str(record.get("record_type", record.get("type", "")))
    if not record_type:
        raise ValueError("Cada registro debe declarar record_type.")
    nested = record.get("values")
    if nested is not None:
        if not isinstance(nested, Mapping):
            raise ValueError("values debe ser un mapping.")
        values = dict(nested)
    else:
        values = {key: value for key, value in record.items() if key not in {"type", "values"}}
    if record_type != "concept":
        values.setdefault("record_type", record_type)
    return record_type, values


def _validate_liquidation_coherence(records: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
    if not records or records[0][0] != "01" or sum(kind == "01" for kind, _ in records) != 1:
        raise ValueError("La liquidación debe comenzar con un único registro 01.")
    header = records[0][1]
    cuit = normalize_cuit_cuil(header.get("cuit"))
    validate_period(header.get("period", ""))
    worker_count = int(str(header.get("worker_count", "")))
    seen: set[str] = set()
    current: str | None = None
    saw_concept = False
    saw_base = False
    for kind, values in records[1:]:
        if kind == "02":
            if current is not None and (not saw_concept or not saw_base):
                raise ValueError(f"Trabajador {current}: requiere conceptos y un registro 04.")
            current = normalize_cuit_cuil(values.get("cuil"))
            if current in seen:
                raise ValueError(f"CUIL duplicado en liquidación: {current}.")
            seen.add(current)
            saw_concept = saw_base = False
        elif kind in {"03", "04", "05", "06"}:
            cuil = normalize_cuit_cuil(values.get("cuil"))
            if current is None or cuil != current:
                raise ValueError(f"Registro {kind} sin trabajador 02 asociado o fuera de orden.")
            if kind == "03":
                if saw_base:
                    raise ValueError("Los conceptos 03 deben preceder al registro 04.")
                saw_concept = True
            elif kind == "04":
                if not saw_concept or saw_base:
                    raise ValueError("Cada trabajador requiere conceptos 03 y un registro 04.")
                saw_base = True
            elif not saw_base:
                raise ValueError(f"El registro {kind} debe seguir al registro 04 del trabajador.")
        else:
            raise ValueError(f"Tipo de registro no admitido en liquidación: {kind}.")
    if current is not None and (not saw_concept or not saw_base):
        raise ValueError(f"Trabajador {current}: requiere conceptos y un registro 04.")
    if len(seen) != worker_count:
        raise ValueError(f"La cabecera declara {worker_count} trabajadores y hay {len(seen)}.")
    if not seen:
        raise ValueError("No hay trabajadores para exportar.")
    if len(cuit) != 11:
        raise ValueError("CUIT de cabecera inválido.")


def generate_file(
    records: Iterable[Mapping[str, Any]],
    *,
    layout_version: str = LAYOUT_VERSION,
    layouts: Mapping[str, RecordLayout] | None = None,
    validate_coherence: bool = True,
) -> bytes:
    parsed = [_record_parts(record) for record in records]
    if validate_coherence:
        _validate_liquidation_coherence(parsed)
    lines = [
        render_record(kind, values, layout_version=layout_version, layouts=layouts)
        for kind, values in parsed
    ]
    payload = ("\r\n".join(lines) + "\r\n").encode(ENCODING, errors="strict")
    return payload


def generate_liquidation_file(
    employer_cuit: str,
    period: date | str,
    workers: Sequence[Mapping[str, Any]],
    *,
    liquidation_number: int = 1,
    layout_version: str = LAYOUT_VERSION,
) -> bytes:
    canonical_cuit = normalize_cuit_cuil(employer_cuit)
    canonical_period = validate_period(period)
    if not workers:
        raise ValueError("No hay trabajadores para exportar.")
    records: list[dict[str, Any]] = [{
        "type": "01",
        "cuit": canonical_cuit,
        "send_id": "SJ",
        "period": canonical_period,
        "liquidation_type": "M",
        "liquidation_number": liquidation_number,
        "base_days": 30,
        "worker_count": len(workers),
    }]
    for worker in workers:
        cuil = normalize_cuit_cuil(worker.get("cuil"))
        records.append({
            "type": "02",
            "cuil": cuil,
            "employee_id": worker.get("employee_id", worker.get("legajo", "")),
            "branch": worker.get("branch", ""),
            "bank_account": worker.get("bank_account", ""),
            "days": worker.get("days", 30),
            "pay_date": worker.get("pay_date", ""),
            "rubric_date": worker.get("rubric_date", ""),
            "payment_method": worker.get("payment_method", ""),
        })
        items = worker.get("items", ())
        if not items:
            raise ValueError(f"Trabajador {cuil}: falta al menos un concepto.")
        for item in items:
            amount = Decimal(str(item.get("amount", item.get("importe", ""))))
            debit_credit = item.get("debit_credit", "D" if amount < 0 else "C")
            records.append({
                "type": "03",
                "cuil": cuil,
                "concept_code": item.get("concept_code", item.get("codigo", "")),
                "quantity": item.get("quantity", item.get("cantidad", "")),
                "unit": item.get("unit", item.get("unidad", "")),
                "amount": abs(amount),
                "debit_credit": debit_credit,
                "adjustment_period": item.get("adjustment_period", ""),
            })
        record04 = dict(worker.get("record04", {}))
        record04.update({"type": "04", "cuil": cuil})
        records.append(record04)
        for event in worker.get("eventual_records", ()):
            records.append({"type": "05", "cuil": cuil, **event})
        for observation in worker.get("observations", ()):
            records.append({"type": "06", "cuil": cuil, "observation": observation})
    return generate_file(records, layout_version=layout_version)


_CONCEPT_FLAGS = (
    "repeat_flag",
    "sipa_ap", "sipa_contrib",
    "inssjyp_ap", "inssjyp_contrib",
    "os_ap", "os_contrib",
    "fsr_ap", "fsr_contrib",
    "renatea_ap", "renatea_contrib",
    "aaff_contrib",
    "fne_contrib",
    "lrt_contrib",
    "dif_ap",
    "esp_ap",
)


def generate_concepts_file(
    concepts: Iterable[Mapping[str, Any]], *, layout_version: str = LAYOUT_VERSION
) -> bytes:
    lines = [
        render_record(
            "concept",
            {
                "arca_code": concept.get("arca_code", ""),
                "employer_code": concept.get("employer_code", ""),
                "description": concept.get("description", ""),
                **{flag: concept.get(flag, "0") for flag in _CONCEPT_FLAGS},
            },
            layout_version=layout_version,
        )
        for concept in concepts
    ]
    if not lines:
        raise ValueError("No hay conceptos para exportar.")
    return ("\r\n".join(lines) + "\r\n").encode(ENCODING, errors="strict")


def preview_file(data: bytes) -> str:
    """Decode a generated file for a text preview without changing its bytes."""
    return data.decode(ENCODING, errors="strict")


def preview_liquidation_file(
    employer_cuit: str,
    period: date | str,
    workers: Sequence[Mapping[str, Any]],
    *,
    liquidation_number: int = 1,
    layout_version: str = LAYOUT_VERSION,
) -> str:
    return preview_file(generate_liquidation_file(
        employer_cuit, period, workers,
        liquidation_number=liquidation_number,
        layout_version=layout_version,
    ))


__all__ = [
    "ENCODING",
    "LAYOUT_VERSION",
    "LAYOUT_VERSIONS",
    "RECORD_LENGTHS",
    "FieldSpec",
    "RecordLayout",
    "generate_concepts_file",
    "generate_file",
    "generate_liquidation_file",
    "preview_file",
    "preview_liquidation_file",
    "render_record",
]
