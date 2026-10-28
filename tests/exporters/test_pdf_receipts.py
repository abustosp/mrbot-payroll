from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from pypdf import PdfReader

from app.exporters.pdf import receipts
from app.exporters.pdf.receipts import (
    ReceiptContextError,
    pdf_backend_status,
    render_receipt_html,
    render_receipt_pdf,
    render_receipts_zip,
)


@pytest.fixture()
def context() -> dict:
    return {
        "receipt_number": "R-2026-09-0001",
        "issue_date": date(2026, 9, 30),
        "period": "Septiembre 2026",
        "employer": {
            "name": "Andes Logística S.A.",
            "cuit": "30-71234567-8",
            "address": "Av. Colón 1234, Córdoba",
            "activity": "Transporte y logística",
        },
        "employee": {
            "name": "María Fernanda Gómez",
            "cuil": "27-30111222-4",
            "file_number": "A-001",
            "category": "Administrativa A",
            "hire_date": date(2018, 3, 12),
            "agreement": "CCT 130/75",
        },
        "items": [
            {
                "code": "SUELDO_BASICO",
                "name": "Sueldo básico",
                "kind": "remunerative",
                "quantity": 1,
                "unit": "mes",
                "amount": "1850000.00",
            },
            {
                "code": "ANTIGUEDAD",
                "name": "Antigüedad",
                "kind": "remunerative",
                "quantity": 5,
                "unit": "años",
                "amount": "185000.00",
            },
            {
                "code": "VIATICOS",
                "name": "Viáticos",
                "kind": "non_remunerative",
                "quantity": 1,
                "unit": "mes",
                "amount": "75000.00",
            },
            {
                "code": "APORTE_JUB",
                "name": "Aporte jubilatorio",
                "kind": "deduction",
                "quantity": 1,
                "unit": "mes",
                "amount": "234025.00",
            },
            {
                "code": "CONTRIB_JUB",
                "name": "Contribución jubilatoria",
                "kind": "contribution",
                "quantity": 1,
                "unit": "mes",
                "amount": "356000.00",
            },
        ],
        "net": "1875975.00",
    }


@pytest.fixture(scope="module")
def pdf_bytes() -> bytes:
    return render_receipt_pdf(
        {
            "receipt_number": "R-2026-09-0001",
            "issue_date": date(2026, 9, 30),
            "period": "Septiembre 2026",
            "employer": {
                "name": "Andes Logística S.A.",
                "cuit": "30-71234567-8",
                "address": "Av. Colón 1234, Córdoba",
                "activity": "Transporte y logística",
            },
            "employee": {
                "name": "María Fernanda Gómez",
                "cuil": "27-30111222-4",
                "file_number": "A-001",
                "category": "Administrativa A",
                "hire_date": date(2018, 3, 12),
                "agreement": "CCT 130/75",
            },
            "items": [
                {
                    "code": "SUELDO_BASICO",
                    "name": "Sueldo básico",
                    "kind": "remunerative",
                    "amount": "1850000.00",
                },
                {
                    "code": "ANTIGUEDAD",
                    "name": "Antigüedad",
                    "kind": "remunerative",
                    "amount": "185000.00",
                },
                {
                    "code": "APORTE_JUB",
                    "name": "Aporte jubilatorio",
                    "kind": "deduction",
                    "amount": "234025.00",
                },
                {
                    "code": "CONTRIB_JUB",
                    "name": "Contribución jubilatoria",
                    "kind": "contribution",
                    "amount": "356000.00",
                },
            ],
            "net": "1985975.00",
        }
    )


def test_render_receipt_html_contains_legal_sections(context: dict) -> None:
    html = render_receipt_html(context)

    assert "Andes Logística S.A." in html
    assert "María Fernanda Gómez" in html
    assert "CUIT: 30-71234567-8" in html
    assert "CUIL" in html
    assert "27-30111222-4" in html
    assert "Septiembre 2026" in html
    assert "Sueldo básico" in html
    assert "Haberes remunerativos" in html
    assert "Haberes no remunerativos" in html
    assert "Descuentos" in html
    assert "Contribuciones del empleador" in html
    assert "Neto a cobrar" in html
    assert "$ 1.875.975,00" in html
    assert "artículo 140" in html
    assert "La emisión de este PDF no acredita" in html


def test_render_receipt_html_escapes_personal_data_and_ignores_unknown_keys(
    context: dict,
) -> None:
    context["employer"]["name"] = 'Empresa <b>"&"</b>'
    context["employee"]["name"] = '<script>alert("xss")</script>'
    context["employee"]["category"] = "<img src=x onerror=alert(1)>"
    context["secret_key"] = "super-secreto-no-debe-salir"
    context["internal_notes"] = "nota interna"

    html = render_receipt_html(context)

    assert '<script>alert("xss")</script>' not in html
    assert "&lt;script&gt;" in html
    assert "Empresa &lt;b&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "super-secreto-no-debe-salir" not in html
    assert "nota interna" not in html


def test_render_receipt_pdf_has_pages_and_extractable_text(pdf_bytes: bytes) -> None:
    assert pdf_bytes.startswith(b"%PDF")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1

    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "María Fernanda Gómez" in text
    assert "Andes Logística" in text
    assert "Recibo de Sueldo" in text
    assert "Neto a cobrar" in text
    assert "Septiembre 2026" in text


def test_render_receipts_zip_contains_one_pdf_per_context_and_deduplicates(
    context: dict,
) -> None:
    second = dict(context)
    second["receipt_number"] = "../../recibo inseguro"

    archive_bytes = render_receipts_zip([context, context, second])

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        assert len(names) == 3
        assert names[0] == "R-2026-09-0001.pdf"
        assert names[1] == "R-2026-09-0001-2.pdf"
        assert all("/" not in name and ".." not in name for name in names)
        assert all(name.endswith(".pdf") for name in names)

        for name in names:
            content = archive.read(name)
            assert content.startswith(b"%PDF")
            reader = PdfReader(io.BytesIO(content))
            assert len(reader.pages) >= 1
            assert "María Fernanda Gómez" in (reader.pages[0].extract_text() or "")


def test_render_receipts_zip_requires_contexts() -> None:
    with pytest.raises(ReceiptContextError):
        render_receipts_zip([])


@pytest.mark.parametrize("missing", ["period", "net"])
def test_missing_required_fields_raise_clear_error(context: dict, missing: str) -> None:
    context.pop(missing)

    with pytest.raises(ReceiptContextError) as excinfo:
        render_receipt_html(context)

    assert missing in str(excinfo.value).lower() or "neto" in str(excinfo.value).lower()


def test_receipt_number_is_optional_for_drafts(context: dict) -> None:
    context.pop("receipt_number")

    html = render_receipt_html(context)

    assert "S/N" in html
    assert "María Fernanda Gómez" in html


def test_render_receipt_html_incluye_neto_en_letras_y_pago(
    context: dict,
) -> None:
    # Art. 140 LCT: el neto va en numeros y letras, con lugar y fecha de pago.
    context["lugar_pago"] = "Córdoba"
    context["fecha_pago"] = date(2026, 9, 30)
    context["banco_deposito"] = "Banco Nación"

    html = render_receipt_html(context)

    assert "Son pesos" in html
    assert "UN MILLON OCHOCIENTOS SETENTA Y CINCO MIL" in html
    assert "Lugar y fecha de pago" in html
    assert "Córdoba" in html
    assert "Banco Nación" in html


def test_unknown_item_kind_is_rejected(context: dict) -> None:
    context["items"][0]["kind"] = "inventado"

    with pytest.raises(ReceiptContextError, match="tipo desconocido"):
        render_receipt_html(context)


def test_invalid_amount_is_rejected(context: dict) -> None:
    context["items"][0]["amount"] = "no-es-un-numero"

    with pytest.raises(ReceiptContextError, match="no es un numero"):
        render_receipt_html(context)


def test_to_decimal_uses_shared_ar_convention() -> None:
    # B-45: "1.234" vale 1234 igual que en importers, no 1.234.
    from decimal import Decimal

    from app.exporters.pdf.receipts import _to_decimal
    from app.importers.parsing import parse_decimal

    assert _to_decimal("1.234") == Decimal("1234")
    assert _to_decimal("1.234") == parse_decimal("1.234")


def test_spanish_aliases_are_supported(context: dict) -> None:
    aliased = {
        "numero_recibo": context["receipt_number"],
        "fecha_emision": context["issue_date"],
        "periodo": context["period"],
        "empleador": context["employer"],
        "trabajador": context["employee"],
        "conceptos": [
            {
                "codigo": "SUELDO_BASICO",
                "nombre": "Sueldo básico",
                "tipo": "remunerativo",
                "cantidad": 1,
                "unidad": "mes",
                "importe": "1850000.00",
            }
        ],
        "neto": "1850000.00",
    }

    html = render_receipt_html(aliased)

    assert "María Fernanda Gómez" in html
    assert "$ 1.850.000,00" in html
    assert "Neto a cobrar" in html


def test_totals_are_derived_from_items_when_not_provided(context: dict) -> None:
    html = render_receipt_html(context)

    assert "$ 2.035.000,00" in html
    assert "$ 75.000,00" in html
    assert "$ 234.025,00" in html
    assert "$ 356.000,00" in html
    assert "$ 1.875.975,00" in html


def test_pdf_backend_status_reports_weasyprint() -> None:
    available, detail = pdf_backend_status()

    assert available is True
    assert "WeasyPrint" in detail


def test_pdf_renderer_unavailable_has_clear_fallback(
    monkeypatch: pytest.MonkeyPatch,
    context: dict,
) -> None:
    def explode():
        raise receipts.PdfRendererUnavailable("WeasyPrint no esta disponible. Use HTML.")

    monkeypatch.setattr(receipts, "_load_weasyprint_html", explode)

    with pytest.raises(receipts.PdfRendererUnavailable, match="WeasyPrint no esta disponible"):
        render_receipt_pdf(context)
