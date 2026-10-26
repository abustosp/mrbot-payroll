"""Importacion pura de empleados y novedades desde CSV/XLSX.

Uso basico::

    from app.importers import analyze_file, import_rows

    preview = analyze_file(archivo, "employees")
    if not preview.errors:
        resultado = import_rows(preview.valid_rows, "employees")
"""

from app.importers.models import (
    DuplicateRow,
    EmployeeRow,
    ImportKind,
    ImportPreview,
    ImportResult,
    NoveltyRow,
    RowError,
    RowModel,
)
from app.importers.parsing import (
    cuil_check_digit,
    is_valid_cuil,
    normalize_cuil,
    parse_date,
    parse_decimal,
    parse_periodo,
)
from app.importers.readers import ImportFileError, Table, read_table
from app.importers.service import analyze_file, import_rows, normalize_kind

__all__ = [
    "DuplicateRow",
    "EmployeeRow",
    "ImportFileError",
    "ImportKind",
    "ImportPreview",
    "ImportResult",
    "NoveltyRow",
    "RowError",
    "RowModel",
    "Table",
    "analyze_file",
    "cuil_check_digit",
    "import_rows",
    "is_valid_cuil",
    "normalize_cuil",
    "normalize_kind",
    "parse_date",
    "parse_decimal",
    "parse_periodo",
    "read_table",
]
