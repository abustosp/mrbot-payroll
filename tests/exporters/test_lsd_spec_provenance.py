"""Procedencia de los diseños TXT: el catálogo AFIP/ARCA fija la especificación.

`normative/lsd/catalog.json` registra los documentos oficiales (URL + SHA-256,
sin binarios versionados). Este test fija que el exportador implementa
exactamente los anchos de ese catálogo, para que la comparación sea
reproducible: si cambia el diseño oficial o el layout, este test lo señala.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.exporters.txt import lsd

CATALOG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "normative" / "lsd" / "catalog.json"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _catalog() -> dict:
    assert CATALOG_PATH.is_file(), f"falta el catálogo de diseños: {CATALOG_PATH}"
    with open(CATALOG_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    assert isinstance(data, dict) and isinstance(data.get("documents"), list)
    return data


def test_catalog_registers_official_sources_with_hashes() -> None:
    """Cada documento oficial tiene URL de ARCA y hash para re-verificar."""
    documents = _catalog()["documents"]
    assert len(documents) == 5
    for document in documents:
        assert document["source_url"].startswith(
            "https://www.afip.gob.ar/LibrodeSueldosDigital/documentos/nuevos/"
        ), document["id"]
        assert _SHA256.fullmatch(document["sha256"] or ""), document["id"]


def test_exporter_widths_match_official_designs() -> None:
    """Los anchos implementados son los del diseño oficial, no una elección."""
    expected: dict[str, int] = {}
    for document in _catalog()["documents"]:
        for record in document.get("records", []):
            kind, width = record.split(":")
            expected[kind] = int(width)
    assert expected == dict(lsd.RECORD_LENGTHS)


def test_layout_version_names_the_official_tool() -> None:
    """La versión interna referencia la herramienta oficial catalogada."""
    tools = {
        document["inner_file"]: document["inner_date"]
        for document in _catalog()["documents"]
        if document.get("inner_file")
    }
    assert tools["LSD-ARMADO-TXT-Liquidaciones.xlsx"] == "2025-09-22"
    assert lsd.LAYOUT_VERSION == "afip-2025.09"
