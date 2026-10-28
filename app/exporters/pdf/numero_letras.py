"""Neto en letras para el recibo (art. 140 LCT: importe en numeros y letras)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

_UNIDADES = (
    "CERO", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE",
    "OCHO", "NUEVE", "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE",
)
_D16_29 = (
    "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE",
    "VEINTIUNO", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO",
    "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE",
)
_DECENAS = {30: "TREINTA", 40: "CUARENTA", 50: "CINCUENTA", 60: "SESENTA",
            70: "SETENTA", 80: "OCHENTA", 90: "NOVENTA"}
_CENTENAS = {100: "CIEN", 200: "DOSCIENTOS", 300: "TRESCIENTOS",
             400: "CUATROCIENTOS", 500: "QUINIENTOS", 600: "SEISCIENTOS",
             700: "SETECIENTOS", 800: "OCHOCIENTOS", 900: "NOVECIENTOS"}
_MAX = 999_999_999_999


def _menor_mil(n: int) -> str:
    if n < 16:
        return _UNIDADES[n]
    if n < 30:
        return _D16_29[n - 16]
    if n < 100:
        decena, resto = divmod(n, 10)
        nombre = _DECENAS[decena * 10]
        return nombre if resto == 0 else f"{nombre} Y {_UNIDADES[resto]}"
    if n == 100:
        return "CIEN"
    centena, resto = divmod(n, 100)
    base = "CIENTO" if centena == 1 else _CENTENAS[centena * 100]
    return base if resto == 0 else f"{base} {_menor_mil(resto)}"


def _entero_a_letras(n: int) -> str:
    if n < 1000:
        return _menor_mil(n)
    if n < 1_000_000:
        miles, resto = divmod(n, 1000)
        base = "MIL" if miles == 1 else f"{_entero_a_letras(miles)} MIL"
        return base if resto == 0 else f"{base} {_entero_a_letras(resto)}"
    millones, resto = divmod(n, 1_000_000)
    base = "UN MILLON" if millones == 1 else f"{_entero_a_letras(millones)} MILLONES"
    return base if resto == 0 else f"{base} {_entero_a_letras(resto)}"


def _apocopar_uno(texto: str) -> str:
    for terminacion, reemplazo in (
        ("VEINTIUNO", "VEINTIUN"), (" Y UNO", " Y UN"), (" UNO", " UN"),
    ):
        if texto.endswith(terminacion):
            return texto[: -len(terminacion)] + reemplazo
    return texto


def numero_a_letras(importe: Decimal | int | str) -> str:
    """Convierte un importe en letras para el recibo ("SON PESOS ...").

    shortcut: cubre hasta 999.999.999.999,99; montos mayores fallan
    explícitamente en vez de abreviarse (ampliar con BILLON si se necesitan).
    """

    try:
        valor = Decimal(str(importe))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"importe inválido {importe!r}") from exc
    if not valor.is_finite() or valor < 0:
        raise ValueError("el importe debe ser un Decimal finito no negativo")
    centavos = int((valor * 100).to_integral_value())
    entero, resto = divmod(centavos, 100)
    if entero > _MAX:
        raise ValueError("importe fuera del rango cubierto (máx. 999.999.999.999,99)")
    if entero == 1:
        letras = "UN PESO"
    else:
        letras = _apocopar_uno(_entero_a_letras(entero))
        letras += " DE PESOS" if entero >= 1_000_000 and entero % 1_000_000 == 0 else " PESOS"
    return f"{letras} CON {resto:02d}/100"
