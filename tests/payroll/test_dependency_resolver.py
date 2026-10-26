import pytest

from app.core.payroll_engine.dependency_resolver import DependencyError, resolve_dependencies
from app.core.payroll_engine.types import FormulaDefinition


def test_resolve_dependencies_is_topological_and_deterministic():
    definitions = [
        FormulaDefinition(code="NETO", formula={"constant": "0"}, depends_on=["BRUTO"]),
        FormulaDefinition(code="BASICO", formula={"constant": "1"}),
        FormulaDefinition(code="BRUTO", formula={"concept": "BASICO"}),
    ]
    assert resolve_dependencies(definitions) == ["BASICO", "BRUTO", "NETO"]


def test_resolve_dependencies_reports_missing_concepts():
    definitions = [FormulaDefinition(code="BRUTO", formula={"concept": "NO_EXISTE"})]
    with pytest.raises(DependencyError, match="missing formula dependency.*NO_EXISTE"):
        resolve_dependencies(definitions)


def test_resolve_dependencies_reports_cycles_with_path():
    definitions = [
        FormulaDefinition(code="A", formula={"constant": "0"}, depends_on=["B"]),
        FormulaDefinition(code="B", formula={"constant": "0"}, depends_on=["A"]),
    ]
    with pytest.raises(DependencyError, match="circular formula dependency: A -> B -> A"):
        resolve_dependencies(definitions)
