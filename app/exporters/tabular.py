"""Descarga tabular de cualquier modulo en csv, xlsx o json."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from fastapi import Response
from openpyxl import Workbook

TABLE_FORMATS = ("csv", "xlsx", "json")

_MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
}

_SUFFIXES = {"csv": "csv", "xlsx": "xlsx", "json": "json"}


def normalize_format(raw: Any) -> str:
    """Valida el formato pedido; falla en 400 si no es csv, xlsx o json."""

    value = str(raw or "").strip().lower()
    if value not in TABLE_FORMATS:
        raise ValueError(
            f"Formato no soportado {raw!r}; use uno de: {', '.join(TABLE_FORMATS)}."
        )
    return value


def _cell(value: Any, *, for_xlsx: bool = False, spreadsheet: bool = False) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value) if for_xlsx else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if spreadsheet and isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_table(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    format: str,
) -> bytes:
    """Serializa filas ya normalizadas al formato pedido."""

    fmt = normalize_format(format)
    if fmt == "json":
        payload = [
            {column: _cell(row.get(column)) for column in columns} for row in rows
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    if fmt == "xlsx":
        book = Workbook()
        sheet = book.active
        sheet.title = "datos"
        sheet.append(list(columns))
        for row in rows:
            sheet.append([
                _cell(row.get(column), for_xlsx=True, spreadsheet=True) for column in columns
            ])
        buffer = io.BytesIO()
        book.save(buffer)
        return buffer.getvalue()
    text_buffer = io.StringIO()
    writer = csv.writer(text_buffer)
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow([_cell(row.get(column), spreadsheet=True) for column in columns])
    return ("\ufeff" + text_buffer.getvalue()).encode("utf-8")


def table_response(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    base_name: str,
    format: str,
) -> Response:
    """Descarga como adjunto la tabla en el formato pedido."""

    fmt = normalize_format(format)
    content = render_table(rows, columns, fmt)
    filename = quote(f"{base_name}-export.{_SUFFIXES[fmt]}", safe="-_.")
    return Response(
        content=content,
        media_type=_MEDIA_TYPES[fmt],
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}'
            ),
            "Cache-Control": "private, no-store",
        },
    )
