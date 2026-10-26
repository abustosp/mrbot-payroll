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


def test_resolve_dependencies_tracks_concept_variable_alias():
    # B-12: {"variable": "concept_B"} is exposed by the calculator, so the
    # resolver must order B before A instead of failing on alphabetical order.
    definitions = [
        FormulaDefinition(code="A", formula={"variable": "concept_B"}),
        FormulaDefinition(code="B", formula={"constant": "10"}),
    ]
    assert resolve_dependencies(definitions) == ["B", "A"]


def test_resolve_dependencies_reports_missing_concept_variable_alias():
    definitions = [
        FormulaDefinition(code="A", formula={"variable": "concept_FANTASMA"}),
    ]
    with pytest.raises(DependencyError, match="missing formula dependency.*FANTASMA"):
        resolve_dependencies(definitions)


def test_resolve_dependencies_ignores_case():
    """B-32: the resolver matches the runtime, which aliases every code."""

    definitions = [
        FormulaDefinition(code="SUELDO_BASICO", formula={"constant": "1000"}),
        FormulaDefinition(
            code="ANTIGUEDAD",
            formula={
                "operator": "multiply",
                "arguments": [{"concept": "sueldo_basico"}, {"constant": "2"}],
            },
        ),
    ]
    assert resolve_dependencies(definitions) == ["SUELDO_BASICO", "ANTIGUEDAD"]


def test_resolve_dependencies_rejects_case_colliding_codes():
    """B-32: two codes differing only by case cannot both exist."""

    definitions = [
        FormulaDefinition(code="Sueldo", formula={"constant": "1"}),
        FormulaDefinition(code="SUELDO", formula={"constant": "2"}),
    ]
    with pytest.raises(DependencyError, match="ignoring case"):
        resolve_dependencies(definitions)
