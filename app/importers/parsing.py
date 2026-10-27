"""Parsers de valores para la importacion de empleados y novedades.

Todas las funciones son puras y no dependen de la base de datos ni del
framework web. Los importes se construyen con :class:`~decimal.Decimal` para no
perder precision y las fechas se devuelven como :class:`datetime.date`.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# Serial de Excel: se descartan valores muy chicos para no confundir un anio
# suelto (por ejemplo 2026) con una fecha. El tope es el ultimo dia del
# calendario de Excel.
SERIAL_MIN_EXCEL = 20000  # 1954-10-03
SERIAL_MAX_EXCEL = 2958465  # 9999-12-31
_EXCEL_EPOCH = date(1899, 12, 30)
_MAX_DECIMAL = Decimal("9999999999999999.99")

_CUIL_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_TIPO_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_BLANK_STRINGS = {"", "nan", "nat", "none", "null"}

_MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_TIPO_ALIASES = {
    "hora_extra": "horas_extra",
    "horas_extras": "horas_extra",
    "hs_extra": "horas_extra",
    "hs_extras": "horas_extra",
    "ausencias": "ausencia",
    "falta": "ausencia",
    "faltas": "ausencia",
    "licencias": "licencia",
    "vacacion": "vacaciones",
    "adelantos": "adelanto",
    "comisiones": "comision",
    "bonificaciones": "bonificacion",
    "bonos": "bonificacion",
    "premios": "bonificacion",
    "embargos": "embargo",
    "suspensiones": "suspension",
    "incapacidades": "incapacidad",
    "aguinaldo": "sac",
    "sueldo_anual_complementario": "sac",
}


def normalize_text(value: Any) -> str:
    """Normaliza un texto para comparaciones: minusculas, sin acentos ni signos.

    Se usa tanto para headers (``"Fecha de ingreso"`` -> ``"fecha de ingreso"``)
    como para valores de tipo de novedad (``"Horas Extra"`` -> ``"horas extra"``).
    """
    text = unicodedata.normalize("NFKD", "" if value is None else str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("_", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def is_blank(value: Any) -> bool:
    """Indica si un valor debe considerarse vacio (incluye NaN y ``"nan"``)."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _BLANK_STRINGS
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, Decimal):
        return value.is_nan()
    return False


def clean_text(value: Any) -> str | None:
    """Convierte un valor a texto recortado; ``None`` para valores vacios."""
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def clean_legajo(value: Any) -> str | None:
    """Normaliza un legajo preservando su representacion textual."""
    text = clean_text(value)
    if text is None:
        return None
    return text


def normalize_cuil(value: Any) -> str | None:
    """Devuelve los 11 digitos de un CUIL/CUIT, o ``None`` si no los tiene."""
    if is_blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return None
        digits = str(int(value))
    else:
        digits = re.sub(r"\D", "", str(value))
    if len(digits) != 11:
        return None
    return digits


def cuil_check_digit(first_ten: str) -> int:
    """Calcula el digito verificador de un CUIL a partir de sus 10 primeros digitos."""
    if len(first_ten) != 10 or not first_ten.isdigit():
        raise ValueError("Se esperaban 10 digitos para calcular el CUIL.")
    total = sum(
        int(digit) * weight
        for digit, weight in zip(first_ten, _CUIL_WEIGHTS, strict=True)
    )
    remainder = total % 11
    check = 11 - remainder
    if check == 11:
        return 0
    if check == 10:
        return 9
    return check


def is_valid_cuil(value: Any) -> bool:
    """Valida un CUIL/CUIT de 11 digitos con su digito verificador."""
    digits = normalize_cuil(value)
    if digits is None or not digits.isdigit():
        return False
    return cuil_check_digit(digits[:10]) == int(digits[10])


def _excel_serial_to_date(serial: int) -> date | None:
    if SERIAL_MIN_EXCEL <= serial <= SERIAL_MAX_EXCEL:
        return _EXCEL_EPOCH + timedelta(days=serial)
    return None


def _build_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def _parse_date_string(text: str) -> date | None:
    text = text.strip().strip("'").strip()
    if not text:
        return None

    # ISO con o sin hora ("2024-03-15", "2024-03-15T12:00:00").
    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T].*)?$", text)
    if iso_match:
        return _build_date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))

    # Formatos con dia primero, con hora opcional.
    day_first = re.match(
        r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})(?:[ T].*)?$", text
    )
    if day_first:
        day, month, year_text = day_first.groups()
        year = int(year_text)
        if len(year_text) == 2:
            year += 2000 if year <= 68 else 1900
        return _build_date(year, int(month), int(day))

    # Formato anio primero con barras o puntos ("2024/03/15").
    year_first = re.match(
        r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})(?:[ T].*)?$", text
    )
    if year_first:
        return _build_date(
            int(year_first.group(1)), int(year_first.group(2)), int(year_first.group(3))
        )

    # Fechas compactas AAAAMMDD o DDMMAAAA.
    compact = re.fullmatch(r"\d{8}", text)
    if compact:
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:])
        parsed = _build_date(year, month, day)
        if parsed is not None:
            return parsed
        return _build_date(int(text[4:]), int(text[2:4]), int(text[:2]))

    # Serial de Excel expresado como texto.
    if text.isdigit():
        return _excel_serial_to_date(int(text))

    return None


def parse_date(value: Any) -> date | None:
    """Convierte fechas en distintos formatos a :class:`datetime.date`.

    Acepta objetos ``date``/``datetime``, seriales de Excel, ``dd/mm/aaaa``,
    ``aaaa-mm-dd`` y variantes con guiones o puntos. Devuelve ``None`` cuando el
    valor no es una fecha valida (por ejemplo ``31/02/2024``).
    """
    if is_blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            integral = int(value)
            if float(integral) != value:
                return None
        number = int(value)
        # Fechas compactas cargadas como numero (20260901).
        if 10000000 <= number <= 99999999:
            return _parse_date_string(str(number))
        return _excel_serial_to_date(number)
    return _parse_date_string(str(value))


def _valid_period(year: int, month: int) -> str | None:
    if not 1900 <= year <= 2100:
        return None
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}{month:02d}"


def parse_periodo(value: Any) -> str | None:
    """Normaliza un periodo de liquidacion a ``AAAAMM``.

    Acepta ``AAAAMM``, ``AAAA-MM``, ``MM/AAAA``, fechas completas, objetos
    ``date``/``datetime`` y seriales de Excel. Devuelve ``None`` si el periodo
    no es valido.
    """
    if is_blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return _valid_period(value.year, value.month)
    if isinstance(value, date):
        return _valid_period(value.year, value.month)

    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return None
        number = int(value)
        if 100000 <= number <= 999999:
            return _valid_period(number // 100, number % 100)
        if 10000000 <= number <= 99999999:
            parsed = parse_date(number)
            return _valid_period(parsed.year, parsed.month) if parsed else None
        parsed = _excel_serial_to_date(number)
        return _valid_period(parsed.year, parsed.month) if parsed else None

    text = str(value).strip().strip("'").strip()
    if not text:
        return None

    compact = re.fullmatch(r"(\d{4})(\d{2})", text)
    if compact:
        return _valid_period(int(compact.group(1)), int(compact.group(2)))

    year_month = re.fullmatch(r"(\d{4})[-/.](\d{1,2})", text)
    if year_month:
        return _valid_period(int(year_month.group(1)), int(year_month.group(2)))

    month_year = re.fullmatch(r"(\d{1,2})[-/.](\d{4})", text)
    if month_year:
        return _valid_period(int(month_year.group(2)), int(month_year.group(1)))

    month_name = re.fullmatch(r"([a-z]+)\s*(?:de\s*)?(\d{4})", normalize_text(text))
    if month_name and month_name.group(1) in _MESES:
        return _valid_period(int(month_name.group(2)), _MESES[month_name.group(1)])

    parsed = parse_date(text)
    if parsed is not None:
        return _valid_period(parsed.year, parsed.month)
    return None


def _normalize_decimal_text(text: str) -> str | None:
    text = text.replace("\u00a0", "")
    text = re.sub(r"(?i)\b(?:ars|usd|eur|uyu)\b", "", text)
    text = text.replace("$", "").replace("+", "")
    text = text.replace(" ", "")
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    if text.startswith("-"):
        negative = True
        text = text[1:]
    elif text.endswith("-"):
        negative = True
        text = text[:-1]
    if not text or not re.fullmatch(r"\d[\d.,]*", text):
        return None

    last_dot = text.rfind(".")
    last_comma = text.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        if last_comma > last_dot:
            integer, _, fractional = text.rpartition(",")
            integer = integer.replace(".", "").replace(",", "")
        else:
            integer, _, fractional = text.rpartition(".")
            integer = integer.replace(",", "").replace(".", "")
        if not integer.isdigit() or not fractional.isdigit():
            return None
        normalized = f"{integer}.{fractional}"
    elif last_dot >= 0 or last_comma >= 0:
        separator = "," if last_comma >= 0 else "."
        parts = text.split(separator)
        if any(not part.isdigit() for part in parts):
            return None
        if len(parts) > 2:
            # Varios separadores solo pueden ser de miles: 1.234.567.
            if all(len(part) == 3 for part in parts[1:]):
                normalized = "".join(parts)
            else:
                return None
        else:
            integer, fractional = parts
            # "1.234" y "1,234" se interpretan como miles; "1234.56" como decimal.
            if len(fractional) == 3 and len(integer) <= 3:
                normalized = integer + fractional
            else:
                normalized = f"{integer}.{fractional}"
    else:
        normalized = text

    if negative:
        return f"-{normalized}"
    return normalized


def _quantize(value: Decimal, places: int | None) -> Decimal:
    if places is None:
        return value
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def parse_decimal(value: Any, *, places: int | None = None) -> Decimal | None:
    """Convierte un valor a ``Decimal`` aceptando formatos argentinos.

    - ``1.234,56`` -> ``1234.56``
    - ``1234.56`` -> ``1234.56``
    - ``1.234`` / ``1,234`` -> ``1234`` (separador de miles)
    - ``1234,56`` -> ``1234.56``
    - ``$ 1.234,56`` y negativos entre parentesis tambien son aceptados.

    ``places`` permite redondear (por ejemplo ``places=2`` para importes).
    """
    if is_blank(value) or isinstance(value, bool):
        return None

    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            return None
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None
    elif isinstance(value, (date, datetime)):
        return None
    else:
        normalized = _normalize_decimal_text(str(value).strip())
        if normalized is None:
            return None
        try:
            number = Decimal(normalized)
        except InvalidOperation:
            return None

    if not number.is_finite() or abs(number) > _MAX_DECIMAL:
        return None
    return _quantize(number, places)


def normalize_tipo(value: Any) -> str | None:
    """Normaliza el tipo de novedad a un codigo ``snake_case``."""
    text = normalize_text(value)
    if not text:
        return None
    code = text.replace(" ", "_")
    code = _TIPO_ALIASES.get(code, code)
    if not _TIPO_RE.fullmatch(code):
        return None
    return code


# B-43: naturaleza de la novedad (gobierna el calculo); sin columna se asume
# remunerativa como hasta ahora. Sin migracion: los valores coinciden con
# PayrollNovelty.kind, ya persistible.
_NATURALEZA_ALIASES = {
    "remunerativo": "REMUNERATIVE",
    "remunerativa": "REMUNERATIVE",
    "remunerative": "REMUNERATIVE",
    "r": "REMUNERATIVE",
    "no remunerativo": "NON_REMUNERATIVE",
    "no remunerativa": "NON_REMUNERATIVE",
    "non remunerative": "NON_REMUNERATIVE",
    "no_remunerativo": "NON_REMUNERATIVE",
    "nr": "NON_REMUNERATIVE",
    "descuento": "DEDUCTION",
    "deduccion": "DEDUCTION",
    "deduction": "DEDUCTION",
    "d": "DEDUCTION",
    "contribucion": "CONTRIBUTION",
    "contribution": "CONTRIBUTION",
    "c": "CONTRIBUTION",
    "auxiliar": "AUXILIARY",
    "auxiliary": "AUXILIARY",
    "aux": "AUXILIARY",
}


def normalize_naturaleza(value: Any) -> str | None:
    """Normaliza la naturaleza a los valores de ``PayrollNovelty.kind``."""
    text = normalize_text(value)
    if not text:
        return None
    return _NATURALEZA_ALIASES.get(text)


def parse_quincena(value: Any) -> int | None:
    """Valida la quincena (1 o 2); ``None`` si esta vacia o es invalida."""
    if is_blank(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, int):
        return value if value in (1, 2) else None
    text = normalize_text(value)
    if text in {"1", "q1", "primera", "primera quincena"}:
        return 1
    if text in {"2", "q2", "segunda", "segunda quincena"}:
        return 2
    return None


def is_valid_email(value: Any) -> bool:
    """Valida de forma basica un email (sin dependencias externas)."""
    text = clean_text(value)
    return bool(text and _EMAIL_RE.fullmatch(text))


# V2-12: prefijos que Excel/LibreOffice interpretan como formula al abrir.
FORMULA_RISK_PREFIXES = ("=", "+", "-", "@")


def is_formula_riesgosa(value: Any) -> bool:
    """Indica si un valor de planilla puede interpretarse como formula.

    Se considera riesgoso todo texto no vacio cuyo primer caracter no
    espacio sea ``=``, ``+``, ``-`` o ``@`` (OWASP CSV Formula Injection).
    """

    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return False
    if isinstance(value, (datetime, date)):
        return False
    text = str(value).lstrip()
    # Un apóstrofe inicial ya neutraliza la fórmula en Excel.
    if text.startswith("'") and len(text) > 1 and text[1] in FORMULA_RISK_PREFIXES:
        return False
    return text.startswith(FORMULA_RISK_PREFIXES)


def contains_html_chars(value: Any) -> bool:
    """Indica si un texto libre contiene ``<`` o ``>`` (V2-13 XSS)."""

    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (datetime, date)):
        return False
    text = str(value)
    return "<" in text or ">" in text
