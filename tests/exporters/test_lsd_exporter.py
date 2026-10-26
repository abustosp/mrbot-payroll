from datetime import date

import pytest

from app.exporters.txt.lsd import (
    ENCODING,
    LAYOUT_VERSION,
    LAYOUT_VERSIONS,
    RECORD_LENGTHS,
    FieldSpec,
    RecordLayout,
    generate_concepts_file,
    generate_liquidation_file,
    preview_file,
    render_record,
)


def make_identifier(prefix: str, tail: int) -> str:
    first_ten = f"{prefix}{tail:08d}"
    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    remainder = 11 - sum(
        int(digit) * weight for digit, weight in zip(first_ten, weights, strict=True)
    ) % 11
    verifier = 0 if remainder == 11 else 9 if remainder == 10 else remainder
    return first_ten + str(verifier)


EMPLOYER = make_identifier("30", 0)
CUIL_1 = make_identifier("20", 12345678)
CUIL_2 = make_identifier("27", 87654321)


@pytest.mark.parametrize(
    ("record_type", "values"),
    [
        ("01", {"cuit": EMPLOYER, "period": "202606", "worker_count": 2}),
        ("02", {"cuil": CUIL_1}),
        ("03", {"cuil": CUIL_1, "concept_code": "BASICO", "amount": "100.25"}),
        ("04", {"cuil": CUIL_1}),
        ("05", {"cuil": CUIL_1}),
        ("06", {"cuil": CUIL_1}),
        ("concept", {"arca_code": "001", "employer_code": "BASICO", "description": "Basico"}),
    ],
)
def test_layouts_have_declared_fixed_lengths(record_type: str, values: dict[str, str]) -> None:
    line = render_record(record_type, values)

    assert len(line) == RECORD_LENGTHS[record_type]
    assert line.isascii()


def test_record_fields_are_configurable_and_support_padding() -> None:
    custom = {
        "X": RecordLayout("X", (
            FieldSpec("record_type", 1, required=True),
            FieldSpec("value", 4, align="right", fill="0"),
        ), 5, version="local-test"),
    }

    assert render_record("X", {"value": "12"}, layouts=custom) == "X0012"


def test_rejects_invalid_cuit_dates_and_non_ascii_text() -> None:
    with pytest.raises(ValueError, match="dígito verificador"):
        render_record("01", {"cuit": "30000000008", "period": "202606", "worker_count": 1})
    with pytest.raises(ValueError, match="fecha inválida"):
        render_record("02", {"cuil": CUIL_1, "pay_date": "20260230"})
    with pytest.raises(ValueError, match="ASCII"):
        render_record("02", {"cuil": CUIL_1, "branch": "Córdoba"})


def test_full_file_for_two_workers_is_latin1_and_length_coherent() -> None:
    content = generate_liquidation_file(
        EMPLOYER,
        date(2026, 6, 20),
        [
            {
                "cuil": CUIL_1,
                "employee_id": "E-1",
                "pay_date": "20260630",
                "items": [{"concept_code": "BASICO", "quantity": 1, "amount": "100000.00"}],
            },
            {
                "cuil": CUIL_2,
                "employee_id": "E-2",
                "pay_date": date(2026, 6, 30),
                "items": [
                    {"concept_code": "BASICO", "quantity": 1, "amount": "110000.00"},
                    {"concept_code": "JUBILACION", "quantity": 1, "amount": "-12100.00"},
                ],
            },
        ],
    )
    text = content.decode(ENCODING)
    lines = text.splitlines()

    assert lines[0][:2] == "01"
    assert int(lines[0][-6:]) == 2
    assert len(lines) == 8
    assert [len(line) for line in lines] == [35, 115, 51, 370, 115, 51, 51, 370]
    assert text.endswith("\r\n")
    assert preview_file(content) == text


def test_concepts_file_uses_195_positions_and_latin1_bytes() -> None:
    payload = generate_concepts_file([{
        "arca_code": "001",
        "employer_code": "BASICO",
        "description": "Sueldo basico",
        "repeat_flag": "1",
        "subsystem_flags": "11110000",
        "is_base": "1",
    }])

    assert len(payload.decode(ENCODING).splitlines()[0]) == RECORD_LENGTHS["concept"]
    assert payload.decode(ENCODING).isascii()
    assert LAYOUT_VERSIONS[LAYOUT_VERSION]["04"].length == 370
