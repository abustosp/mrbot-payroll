"""Convert salary scale rows into reviewable DSL proposals."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.ai.hashing import compute_content_hash
from app.ai.schemas import (
    DocumentMetadata,
    ParameterUnit,
    ProposedFormula,
    ProposedParameter,
    SourceReference,
    SuggestedTest,
)


def sanitize_category_code(category_code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", category_code.upper())


def parse_scales(
    rows: list[dict], metadata: DocumentMetadata | dict
) -> tuple[list[ProposedParameter], list[ProposedFormula], list[str]]:
    metadata = DocumentMetadata.model_validate(metadata)
    parameters: list[ProposedParameter] = []
    formulas: list[ProposedFormula] = []
    skipped: list[str] = []

    for index, row in enumerate(rows, start=1):
        try:
            category = row.get("category_code")
            if not isinstance(category, str) or not category.strip():
                raise ValueError("category_code is missing")
            category = sanitize_category_code(category)
            if not category.strip("_"):
                raise ValueError("category_code has no alphanumeric characters")
            code = f"SUELDO_BASICO_{category}"

            amount = row.get("amount")
            if not isinstance(amount, (str, int, Decimal)) or isinstance(amount, bool):
                raise ValueError("amount must be an exact decimal, not a float")
            try:
                amount = Decimal(amount)
            except InvalidOperation as exc:
                raise ValueError("amount is not a decimal") from exc
            if not amount.is_finite() or amount <= 0:
                raise ValueError("amount must be a finite positive decimal")

            # El hash se calcula sobre la fila exacta analizada, nunca se
            # confia en un hash provisto por el modelo o por el llamante.
            source = SourceReference(
                document_id=metadata.document_id,
                version=metadata.version,
                article=row.get("source_table"),
                content_hash=compute_content_hash(
                    json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                ),
            )
            parameter = ProposedParameter(
                code=code,
                name=code,
                value=str(amount),
                unit=ParameterUnit.CURRENCY,
                source=source,
                effective_from=row.get("valid_from"),
                effective_to=row.get("valid_to"),
            )
            formula = ProposedFormula(
                code=code,
                formula={"parameter": code},
                source=source,
                effective_from=parameter.effective_from,
                effective_to=parameter.effective_to,
                tests=[SuggestedTest(inputs={}, expected=str(amount))],
            )
        except (ValueError, ValidationError) as exc:
            skipped.append(f"row {index}: {exc}")
            continue
        parameters.append(parameter)
        formulas.append(formula)

    return parameters, formulas, skipped
