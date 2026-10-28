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
        ("concept", {"arca_code": "110000", "employer_code": "BASICO", "description": "Sueldo"}),
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
        "arca_code": "110000",
        "employer_code": "BASICO",
        "description": "Sueldo basico",
        "repeat_flag": "1",
        "sipa_ap": "1",
        "sipa_contrib": "1",
        "os_ap": "1",
        "os_contrib": "1",
    }])

    assert len(payload.decode(ENCODING).splitlines()[0]) == RECORD_LENGTHS["concept"]
    assert payload.decode(ENCODING).isascii()
    assert LAYOUT_VERSIONS[LAYOUT_VERSION]["04"].length == 370


def test_official_layout_offsets_match_afip_build_tools() -> None:
    """Byte-exact offsets from the AFIP LSD-ARMADO-TXT planillas.

    06 = 93 (2+11+80, obs left-padded with zeros, no period field);
    concept = 195 with flags at fixed 1-based positions 167-186.
    """
    line06 = render_record("06", {"cuil": CUIL_1, "observation": "OBS"})
    assert len(line06) == 93
    assert line06[:13] == "06" + CUIL_1
    assert line06[13:] == "0" * 77 + "OBS"

    concept = generate_concepts_file([{
        "arca_code": "110000",
        "employer_code": "R00001",
        "description": "Sueldo Basico",
        "repeat_flag": "1",
        "sipa_ap": "1",
        "sipa_contrib": "1",
        "inssjyp_ap": "1",
        "inssjyp_contrib": "1",
        "os_ap": "1",
        "os_contrib": "1",
        "fsr_ap": "1",
        "fsr_contrib": "1",
        "renatea_ap": "1",
        "renatea_contrib": "1",
        "aaff_contrib": "1",
        "fne_contrib": "1",
        "lrt_contrib": "1",
        "dif_ap": "0",
        "esp_ap": "0",
    }]).decode(ENCODING).splitlines()[0]
    assert len(concept) == 195
    assert concept[0:6] == "110000"
    assert concept[6:16] == "R00001    "
    assert concept[16:166] == "Sueldo Basico" + " " * 137
    assert concept[166] == "1"
    assert concept[167:177] == "1" * 10
    assert concept[177] == " "
    assert concept[178] == "1"
    assert concept[179] == " "
    assert concept[180] == "1"
    assert concept[181] == " "
    assert concept[182] == "1"
    assert concept[183] == "0"
    assert concept[184] == " "
    assert concept[185] == "0"
    assert concept[186:] == " " * 9

    line02 = render_record("02", {"cuil": CUIL_1, "bank_account": "123"})
    assert len(line02) == 115
    assert line02[73:95] == " " * 19 + "123"

    line04 = render_record(
        "04", {"cuil": CUIL_1, "activity": "1", "locality": "2", "health_plan": "3"}
    )
    assert len(line04) == 370
    assert line04[25:28] == "001"
    assert line04[33:35] == "02"
    assert line04[62:68] == "000003"

def test_official_empty_field_padding() -> None:
    """Campos vacíos según la herramienta oficial: período de ajuste con
    espacios; banderas numéricas, fechas de pago y códigos con ceros."""
    line03 = render_record("03", {"cuil": CUIL_1, "concept_code": "X", "amount": "1.00"})
    assert len(line03) == 51
    assert line03[45:] == " " * 6

    line04 = render_record("04", {"cuil": CUIL_1})
    assert len(line04) == 370
    assert line04[13] == "0"
    assert line04[14:16] == "00"
    assert line04[23:25] == "  "
    assert line04[25:28] == "000"
    assert line04[28:31] == "   "
    assert line04[33:35] == "00"
    assert line04[35:37] == "00"

    line02 = render_record("02", {"cuil": CUIL_1})
    assert len(line02) == 115
    assert line02[98:106] == "00000000"
    assert line02[106:114] == " " * 8
    assert line02[114] == "0"


    line05 = render_record(
        "05",
        {
            "cuil": CUIL_1,
            "category": "12",
            "position": "3",
            "start_date": "20260601",
            "end_date": "20260630",
            "amount": "100000.00",
            "employer_cuit": EMPLOYER,
        },
    )
    assert len(line05) == 65
    assert line05[:13] == "05" + CUIL_1
    assert line05[13:19] == "000012"
    assert line05[19:23] == "0003"
    assert line05[23:39] == "2026060120260630"
    assert line05[39:54] == "000000010000000"
    assert line05[54:] == EMPLOYER
