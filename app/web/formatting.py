"""Helpers de presentacion compartidos por la interfaz web."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

_STATUS_LABELS: dict[str, dict[str, str]] = {
    "company": {
        "active": "Activa",
        "inactive": "Inactiva",
    },
    "employee": {
        "active": "Activo",
        "inactive": "Inactivo",
        "leave": "Con licencia",
    },
    "agreement": {
        "active": "Vigente",
        "review": "En revisión",
        "draft": "Borrador",
    },
    "payroll": {
        "draft": "Borrador",
        "calculated": "Calculada",
        "review": "En revisión",
        "approved": "Aprobada",
        "closed": "Cerrada",
        "annulled": "Anulada",
    },
    "proposal": {
        "draft": "Borrador",
        "in_review": "En revisión",
        "approved": "Aprobada",
        "rejected": "Rechazada",
    },
    "receipt": {
        "issued": "Emitido",
        "pending": "Pendiente",
        "cancelled": "Anulado",
    },
    "health": {
        "ok": "Operativo",
        "degraded": "Degradado",
        "error": "Con errores",
        "demo": "Demo",
    },
}

_DEFAULT_LABELS = {
    "active": "Activo",
    "inactive": "Inactivo",
    "draft": "Borrador",
    "calculated": "Calculada",
    "review": "En revisión",
    "in_review": "En revisión",
    "approved": "Aprobada",
    "rejected": "Rechazada",
    "closed": "Cerrada",
    "annulled": "Anulada",
    "issued": "Emitido",
    "pending": "Pendiente",
    "ok": "Operativo",
    "degraded": "Degradado",
    "error": "Con errores",
    "demo": "Demo",
}

_STATUS_CLASSES = {
    "active": "success",
    "approved": "success",
    "closed": "success",
    "issued": "success",
    "ok": "success",
    "calculated": "info",
    "review": "warning",
    "in_review": "warning",
    "pending": "warning",
    "draft": "neutral",
    "demo": "info",
    "degraded": "warning",
    "inactive": "danger",
    "rejected": "danger",
    "cancelled": "danger",
    "annulled": "danger",
    "error": "danger",
}

_KIND_LABELS = {
    "remunerative": "Remunerativo",
    "non_remunerative": "No remunerativo",
    "deduction": "Descuento",
    "contribution": "Contribución",
}


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def money(value: Any) -> str:
    """Formatea un importe en estilo argentino (``$ 1.234.567,89``)."""

    amount = to_decimal(value)
    if amount is None:
        return "—"
    negative = amount < 0
    amount = abs(amount)
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if negative else ''}$ {formatted}"


def quantity(value: Any) -> str:
    amount = to_decimal(value)
    if amount is None:
        return "—"
    if amount == amount.to_integral_value():
        return f"{amount:,.0f}".replace(",", ".")
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def percent(value: Any) -> str:
    amount = to_decimal(value)
    if amount is None:
        return "—"
    formatted = f"{amount:.1f}".replace(".", ",")
    return f"{formatted}%"


def progress_width(value: Any, maximum: Any = 100) -> str:
    """Devuelve un ancho CSS acotado y seguro para barras de progreso."""

    amount = to_decimal(value)
    top = to_decimal(maximum) or Decimal("100")
    if amount is None or top <= 0:
        return "0%"
    bounded = max(Decimal("0"), min(amount, top))
    percentage = (bounded / top) * 100
    return f"{percentage:.1f}%"


def date_ar(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw


def period_ar(value: Any) -> str:
    """Convierte ``2026-09`` en ``09/2026``."""

    raw = str(value or "").strip()
    if len(raw) == 7 and raw[4] == "-":
        return f"{raw[5:7]}/{raw[:4]}"
    return raw or "—"


def status_label(status: str, domain: str = "") -> str:
    domain_labels = _STATUS_LABELS.get(domain.strip().casefold(), {})
    key = str(status or "").strip().casefold()
    return domain_labels.get(key) or _DEFAULT_LABELS.get(key) or key.replace("_", " ").title()


def status_class(status: str) -> str:
    return _STATUS_CLASSES.get(str(status or "").strip().casefold(), "neutral")


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(str(kind or "").strip().casefold(), kind)


def initials(name: str) -> str:
    parts = [part for part in str(name or "").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def truncate(value: Any, length: int = 90) -> str:
    text = str(value or "").strip()
    if len(text) <= length:
        return text
    return text[: max(length - 1, 0)].rstrip() + "…"


__all__ = [
    "date_ar",
    "initials",
    "kind_label",
    "money",
    "percent",
    "period_ar",
    "progress_width",
    "quantity",
    "status_class",
    "status_label",
    "to_decimal",
    "truncate",
]
