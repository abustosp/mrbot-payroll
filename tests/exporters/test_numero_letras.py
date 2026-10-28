"""Neto en letras para el recibo (art. 140 LCT, inc. G)."""

from __future__ import annotations

from decimal import Decimal

from app.exporters.pdf.numero_letras import numero_a_letras


def test_oraculo_guia_neto_en_letras() -> None:
    assert numero_a_letras(Decimal("37284.45")) == (
        "TREINTA Y SIETE MIL DOSCIENTOS OCHENTA Y CUATRO PESOS CON 45/100"
    )


def test_casos_borde() -> None:
    assert numero_a_letras(Decimal("1.00")) == "UN PESO CON 00/100"
    assert numero_a_letras(Decimal("1000000.00")) == "UN MILLON DE PESOS CON 00/100"
    assert numero_a_letras(Decimal("1875975.00")) == (
        "UN MILLON OCHOCIENTOS SETENTA Y CINCO MIL NOVECIENTOS "
        "SETENTA Y CINCO PESOS CON 00/100"
    )
