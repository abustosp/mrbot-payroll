"""Shared fixtures for the AI test suite. No network and no production data."""

from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime

import pytest

from app.ai.analysis import analyze_agreement
from app.ai.hashing import compute_content_hash
from app.ai.providers import MockProvider
from app.ai.schemas import DocumentMetadata, LLMUsage

DOCUMENT_ID = "cct-130-75"
DOCUMENT_VERSION = "2026-10"
ANALYSIS_NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def base_payload() -> dict:
    """A valid model response for the illustrative agreement."""

    source = {
        "document_id": DOCUMENT_ID,
        "version": DOCUMENT_VERSION,
        "page": 12,
        "article": "Articulo 15",
    }
    return {
        "summary": "Convenio de comercio con adicional por antiguedad.",
        "agreement_number": "CCT 130/75",
        "agreement_title": "Empleados de Comercio",
        "jurisdiction": "Argentina",
        "effective_from": "2026-01-01",
        "effective_to": None,
        "concepts": [
            {
                "code": "SUELDO_BASICO",
                "name": "Sueldo basico",
                "description": "Remuneracion basica de la categoria.",
                "nature": "REMUNERATIVE",
                "source": dict(source, page=3, article="Articulo 12"),
                "effective_from": "2026-01-01",
                "effective_to": None,
                "notes": [],
            }
        ],
        "parameters": [
            {
                "code": "PORCENTAJE_ANTIGUEDAD",
                "name": "Porcentaje por anio de antiguedad",
                "description": "Uno por ciento del basico por anio.",
                "value": "0.01",
                "unit": "percentage",
                "source": dict(source),
                "effective_from": "2026-01-01",
                "effective_to": None,
                "notes": [],
            }
        ],
        "formulas": [
            {
                "code": "ANTIGUEDAD",
                "description": "Adicional por antiguedad",
                "formula": {
                    "operator": "multiply",
                    "arguments": [
                        {"variable": "sueldo_basico"},
                        {"variable": "anios_antiguedad"},
                        {"parameter": "PORCENTAJE_ANTIGUEDAD"},
                    ],
                },
                "conditions": [
                    {
                        "field": "anios_antiguedad",
                        "operator": "greater_than",
                        "value": 0,
                    }
                ],
                "rounding": {"decimals": 2, "mode": "HALF_UP"},
                "variables": ["sueldo_basico", "anios_antiguedad"],
                "depends_on": [],
                "nature": "REMUNERATIVE",
                "source": dict(source),
                "effective_from": "2026-01-01",
                "effective_to": None,
                "tests": [
                    {
                        "name": "caso base",
                        "inputs": {
                            "sueldo_basico": "1000000",
                            "anios_antiguedad": "5",
                        },
                        "expected": "50000",
                        "period": "2026-06-01",
                    }
                ],
            }
        ],
        "ambiguities": ["La base de calculo debe confirmarse con el area legal."],
        "notes": [],
    }


def make_payload() -> dict:
    return copy.deepcopy(base_payload())


@pytest.fixture
def metadata() -> DocumentMetadata:
    return DocumentMetadata(
        document_id=DOCUMENT_ID,
        version=DOCUMENT_VERSION,
        title="CCT 130/75",
        jurisdiction="Argentina",
    )


@pytest.fixture
def payload() -> dict:
    return make_payload()


@pytest.fixture
def document_text() -> str:
    return (
        "CONVENIO COLECTIVO 130/75\n"
        "Articulo 12: el sueldo basico de la categoria A es de $1.000.000.\n"
        "Articulo 15: adicional por antiguedad del 1% por cada anio.\n"
    )


@pytest.fixture
def analysis(metadata, document_text, payload):
    return analyze_agreement(
        document_text,
        MockProvider(json.dumps(payload)),
        metadata,
        now=ANALYSIS_NOW,
    )


@pytest.fixture
def mock_usage() -> LLMUsage:
    return LLMUsage(
        provider="mock",
        model="mock-model",
        prompt_tokens=1200,
        completion_tokens=300,
        total_tokens=1500,
        cost_usd="0.0025",
    )


@pytest.fixture
def valid_source() -> dict:
    return {
        "document_id": DOCUMENT_ID,
        "version": DOCUMENT_VERSION,
        "page": 12,
        "article": "Articulo 15",
        "content_hash": compute_content_hash("document"),
    }


@pytest.fixture
def fixed_now() -> datetime:
    return ANALYSIS_NOW


@pytest.fixture
def valid_date() -> date:
    return date(2026, 1, 1)
