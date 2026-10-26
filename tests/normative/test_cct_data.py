import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.payroll_engine.formula_engine import evaluate_formula
from app.core.payroll_engine.types import FormulaContext, FormulaDefinition
from app.core.payroll_engine.validations import validate_formula

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CATALOG_PATH = BASE_DIR / "normative" / "cct" / "catalog.json"
FORMULAS_PATH = BASE_DIR / "normative" / "cct" / "formulas.json"
PDFS_DIR = BASE_DIR / "normative" / "cct" / "pdfs"


@pytest.fixture(scope="module")
def catalog_data() -> list[dict]:
    assert CATALOG_PATH.exists(), f"catalog.json not found at {CATALOG_PATH}"
    with open(CATALOG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list), "catalog.json must contain a list of CCTs"
    return data


@pytest.fixture(scope="module")
def formulas_data() -> list[dict]:
    assert FORMULAS_PATH.exists(), f"formulas.json not found at {FORMULAS_PATH}"
    with open(FORMULAS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list), "formulas.json must contain a list of formulas"
    return data


def test_catalog_contains_exactly_10_ccts(catalog_data: list[dict]):
    assert len(catalog_data) == 10, f"Expected 10 CCTs, got {len(catalog_data)}"
    codes = [item.get("code") for item in catalog_data]
    assert len(set(codes)) == 10, f"Duplicate CCT codes found: {codes}"


def test_catalog_has_required_fields_and_sources(catalog_data: list[dict]):
    required_fields = {
        "code", "name", "activity", "scope", "source_urls",
        "pdf_path", "pdf_sha256", "pdf_status", "categories",
        "salary_scales", "formula_codes", "confidence", "notes"
    }
    for cct in catalog_data:
        code = cct.get("code", "UNKNOWN")
        missing = required_fields - set(cct.keys())
        assert not missing, f"CCT {code} is missing required fields: {missing}"
        assert cct["code"], f"CCT {code} has empty code"
        assert cct["name"], f"CCT {code} has empty name"
        assert cct["activity"], f"CCT {code} has empty activity"
        assert cct["scope"], f"CCT {code} has empty scope"
        assert isinstance(cct["source_urls"], list) and len(cct["source_urls"]) > 0, (
            f"CCT {code} must have at least one source URL"
        )
        assert isinstance(cct["categories"], list) and len(cct["categories"]) > 0, (
            f"CCT {code} must define at least one category"
        )
        assert cct["confidence"] in {"high", "medium", "low"}, (
            f"CCT {code} has invalid confidence: {cct['confidence']}"
        )


def test_pdfs_exist_and_start_with_pdf_header(catalog_data: list[dict]):
    total_size = 0
    max_size_bytes = 50 * 1024 * 1024  # 50 MB total limit

    for cct in catalog_data:
        code = cct["code"]
        rel_path = cct["pdf_path"]
        pdf_file = BASE_DIR / rel_path
        assert pdf_file.exists(), f"PDF file for CCT {code} does not exist at {pdf_file}"

        data = pdf_file.read_bytes()
        assert data.startswith(b"%PDF"), (
            f"PDF file for CCT {code} does not start with %PDF header: {data[:10]}"
        )

        file_sha256 = hashlib.sha256(data).hexdigest()
        assert file_sha256 == cct["pdf_sha256"], (
            f"Checksum mismatch for CCT {code}: catalog={cct['pdf_sha256']}, actual={file_sha256}"
        )
        assert cct["pdf_status"] == "verified", (
            f"CCT {code} pdf_status must be 'verified', got {cct['pdf_status']}"
        )
        total_size += len(data)

    assert total_size <= max_size_bytes, (
        f"Total size of PDFs exceeds 50 MB: {total_size / (1024 * 1024):.2f} MB"
    )


def test_salary_scales_have_source_and_validity(catalog_data: list[dict]):
    for cct in catalog_data:
        code = cct["code"]
        scales = cct.get("salary_scales", [])
        assert isinstance(scales, list) and len(scales) > 0, (
            f"CCT {code} must have at least one salary scale entry"
        )
        for index, scale in enumerate(scales):
            assert "categoria" in scale and scale["categoria"], (
                f"CCT {code} scale {index} missing categoria"
            )
            assert scale.get("moneda") == "ARS", f"CCT {code} scale {index} moneda must be 'ARS'"
            assert "vigencia_desde" in scale and scale["vigencia_desde"], (
                f"CCT {code} scale {index} missing vigencia_desde"
            )
            assert "fuente" in scale and scale["fuente"], (
                f"CCT {code} scale {index} missing fuente"
            )
            assert scale.get("estado") == "verified", (
                f"CCT {code} scale {index} must be verified"
            )
            assert scale.get("source_id"), (
                f"CCT {code} scale {index} missing source_id"
            )
            assert scale.get("verification_source"), (
                f"CCT {code} scale {index} missing verification_source"
            )
            assert scale.get("importe") is not None, (
                f"CCT {code} scale {index} verified scale must have non-null importe"
            )
            assert Decimal(str(scale["importe"])) > Decimal("0"), (
                f"CCT {code} scale {index} importe must be positive"
            )
            assert "estimated_value" not in scale, (
                f"CCT {code} scale {index} must not contain estimated_value"
            )


def test_verified_scales_must_have_valid_verification_source(catalog_data: list[dict]):
    """Every scale with estado == verified must have a valid verification_source

    pointing to an existing local PDF or a valid official URL.
    """
    verified_count = 0
    for cct in catalog_data:
        code = cct["code"]
        for index, scale in enumerate(cct.get("salary_scales", [])):
            if scale.get("estado") == "verified":
                verified_count += 1
                source = scale.get("verification_source")
                assert source and isinstance(source, str), (
                    f"CCT {code} scale {index} is verified but has empty verification_source"
                )
                if source.startswith("http://") or source.startswith("https://"):
                    assert len(source) > 10, f"CCT {code} scale {index} has invalid source URL"
                else:
                    local_path = BASE_DIR / source
                    assert local_path.exists(), (
                        f"CCT {code} scale {index} verification_source file does not exist: {local_path}"
                    )
    assert verified_count > 0, "Catalog must contain at least one verified salary scale"


def test_no_null_importe_marked_as_verified(catalog_data: list[dict]):
    """The catalog contains verified scales only, each with a concrete amount."""
    for cct in catalog_data:
        code = cct["code"]
        for index, scale in enumerate(cct.get("salary_scales", [])):
            assert scale.get("estado") == "verified", (
                f"CCT {code} scale {index} is not verified"
            )
            assert scale.get("importe") is not None, (
                f"CCT {code} scale {index} is verified but has null importe"
            )


def test_future_scales_have_a_verified_source(catalog_data: list[dict]):
    """Future scheduled scales keep their verified source and may start after today."""
    for cct in catalog_data:
        code = cct["code"]
        for index, scale in enumerate(cct.get("salary_scales", [])):
            assert scale.get("verification_source"), (
                f"CCT {code} scale {index} missing official source"
            )
            if scale.get("vigencia_desde", "") > "2026-10-26":
                assert scale.get("estado") == "verified"


def test_verification_audit_metrics(catalog_data: list[dict]):
    """Check each CCT's verified count against its evidence metadata."""
    for cct in catalog_data:
        scales = cct.get("salary_scales", [])
        assert len(scales) == cct["evidence_scales_verified"]
        assert all(scale["estado"] == "verified" for scale in scales)


def test_formulas_file_has_at_least_10_formulas(formulas_data: list[dict]):
    assert len(formulas_data) >= 10, f"Expected at least 10 formulas, found {len(formulas_data)}"
    codes = [item.get("code") for item in formulas_data]
    assert len(set(codes)) == len(codes), f"Duplicate formula codes found: {codes}"


def test_each_formula_validates_against_pydantic_and_dsl_engine(formulas_data: list[dict]):
    for item in formulas_data:
        code = item.get("code", "UNKNOWN")
        # 1. Pydantic model validation
        definition = FormulaDefinition.model_validate(item)
        assert definition.code == code
        assert definition.source, f"Formula {code} must have a non-empty source"

        # 2. DSL engine static structure validation
        errors = validate_formula(definition)
        assert not errors, f"DSL validation errors for formula {code}: {errors}"


def test_each_formula_passes_unit_tests(formulas_data: list[dict]):
    for item in formulas_data:
        definition = FormulaDefinition.model_validate(item)
        tests = item.get("tests", [])
        assert len(tests) > 0, f"Formula {definition.code} must include at least one unit test"

        for test_idx, test_case in enumerate(tests):
            context = FormulaContext(
                variables=test_case.get("variables", {}),
                parameters=test_case.get("parameters", {}),
                concepts=test_case.get("concepts", {}),
            )
            result = evaluate_formula(definition, context)
            expected = Decimal(str(test_case["expected"]))
            assert result.value == expected, (
                f"Formula {definition.code} test {test_idx + 1} failed: "
                f"expected {expected}, got {result.value}"
            )
