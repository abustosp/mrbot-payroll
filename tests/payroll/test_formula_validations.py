from app.core.payroll_engine.types import FormulaContext, FormulaDefinition
from app.core.payroll_engine.validations import validate_formula


def test_validate_formula_reports_unknown_operator_arity_and_missing_inputs():
    definition = FormulaDefinition(
        code="INVALIDA",
        formula={"operator": "power", "arguments": [{"variable": "sueldo"}]},
        conditions=[{"field": "anios", "operator": "greater_than", "value": 0}],
    )
    errors = validate_formula(definition, FormulaContext())
    assert any("unknown operator 'power'" in error for error in errors)
    assert any("missing variable 'sueldo'" in error for error in errors)
    assert any("missing variable 'anios'" in error for error in errors)


def test_validate_formula_reports_type_mismatch_and_missing_concept():
    definition = FormulaDefinition(
        code="TIPOS",
        formula={"operator": "add", "arguments": [
            {"variable": "activo"}, {"concept": "BASICO"},
        ]},
    )
    errors = validate_formula(definition, FormulaContext(variables={"activo": True}))
    assert any("requires a number, got boolean" in error for error in errors)
    assert any("missing concept 'BASICO'" in error for error in errors)


def test_validate_formula_finds_dependency_cycle():
    definition = FormulaDefinition(code="A", formula={"concept": "A"})
    errors = validate_formula(definition)
    assert any("circular formula dependency" in error for error in errors)


def test_validate_formula_accepts_case_insensitive_references():
    """B-32: validation accepts the same spellings the runtime resolves."""

    definition = FormulaDefinition(
        code="ANTIGUEDAD",
        formula={
            "operator": "multiply",
            "arguments": [{"concept": "sueldo_basico"}, {"constant": "2"}],
        },
    )
    context = FormulaContext(
        variables={"SUELDO_BASICO": 1000},
        parameters={"Tasa": 2},
        concepts={"SUELDO_BASICO": 1000},
    )
    assert validate_formula(definition, context) == []


def test_validate_formula_rejects_excessive_depth():
    """B-33: a 600-deep tree is a domain error, never a RecursionError."""

    expression: object = {"constant": "1"}
    for _ in range(600):
        expression = {"operator": "add", "arguments": [expression, {"constant": "1"}]}
    definition = FormulaDefinition(code="DEEP", formula=expression)

    errors = validate_formula(definition)

    assert any("maximum nesting depth" in error for error in errors)
