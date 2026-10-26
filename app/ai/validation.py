"""Deterministic validation for proposed formulas.

Validation is structural and never executes the formula. When the payroll
engine exposes ``validate_formula``, this module calls it defensively and merges
its findings; otherwise the report states that limitation explicitly.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ai.schemas import (
    AgreementAnalysis,
    ProposalStatus,
    ProposedFormula,
    ValidationIssue,
    ValidationReport,
)

VALIDATOR_VERSION = "1.0"

DSL_OPERATORS = frozenset(
    {
        "add",
        "subtract",
        "multiply",
        "divide",
        "percentage",
        "min",
        "max",
        "abs",
        "round",
        "floor",
        "ceil",
        "if",
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "and",
        "or",
        "not",
        "coalesce",
    }
)
CONDITION_OPERATORS = frozenset(
    {
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
    }
)
_LEAF_KEYS = frozenset({"variable", "parameter", "concept", "constant"})
_UNSAFE_KEYS = frozenset(
    {"python", "py", "eval", "exec", "lambda", "import", "call", "function", "code"}
)
_OPERATOR_KEYS = frozenset({"operator", "arguments"})
_ARITY_EXACT = {
    "subtract": 2,
    "divide": 2,
    "percentage": 2,
    "abs": 1,
    "floor": 1,
    "ceil": 1,
    "if": 3,
    "eq": 2,
    "ne": 2,
    "gt": 2,
    "gte": 2,
    "lt": 2,
    "lte": 2,
    "equals": 2,
    "not_equals": 2,
    "greater_than": 2,
    "greater_than_or_equal": 2,
    "less_than": 2,
    "less_than_or_equal": 2,
    "not": 1,
}
_ARITY_MIN = {
    "add": 2,
    "multiply": 2,
    "min": 1,
    "max": 1,
    "coalesce": 1,
    "and": 2,
    "or": 2,
}
_ENGINE_LIMITATION = (
    "Structural DSL validation only: "
    "app.core.payroll_engine.validations.validate_formula is not available, so "
    "the formula was not checked by the payroll engine."
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _issue(code: str, message: str, path: str = "") -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message[:2000],
        path=path[:1000],
    )


def validate_formula_proposal(
    formula: ProposedFormula,
    *,
    analysis: AgreementAnalysis | None = None,
    known_variables: Iterable[str] = (),
    known_parameters: Iterable[str] = (),
    known_concepts: Iterable[str] = (),
    now: datetime | None = None,
) -> ValidationReport:
    """Validate a formula proposal without executing or approving it."""

    if not isinstance(formula, ProposedFormula):
        raise TypeError("validate_formula_proposal expects a ProposedFormula")

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    limitations: list[str] = []
    checks = [
        "schema",
        "source_traceability",
        "formula_dsl",
        "dependencies",
        "validity_period",
        "suggested_tests",
    ]

    _validate_source(formula, analysis, errors, warnings)
    references = _validate_dsl_tree(formula.formula, errors)
    _validate_conditions(formula.conditions, references, errors)
    _validate_variable_declarations(
        formula, references, set(known_variables), errors, warnings
    )

    analysis_formulas = (
        {item.code: item for item in analysis.formulas} if analysis is not None else {}
    )
    _validate_dependencies(
        formula,
        analysis,
        analysis_formulas,
        references,
        errors,
        warnings,
    )
    _validate_parameter_and_concept_references(
        formula,
        analysis,
        references,
        set(known_parameters),
        set(known_concepts),
        errors,
        warnings,
    )
    _validate_dates(formula, analysis, errors, warnings)
    _validate_tests(formula, references, errors, warnings)

    engine_errors, engine_notes, engine_name = _run_engine_validator(formula)
    errors.extend(engine_errors)
    if engine_name:
        checks.append("engine_formula_validator")
    else:
        limitations.extend(engine_notes)
    limitations.append(
        "Suggested tests are recorded for human or engine review; the AI package "
        "never executes formulas."
    )

    return ValidationReport(
        is_valid=not errors,
        formula_code=formula.code,
        errors=errors,
        warnings=warnings,
        checks=checks,
        limitations=limitations,
        engine_validator=engine_name,
        validated_at=now or _utcnow(),
        validator_version=VALIDATOR_VERSION,
    )


def validate_proposal(
    formula: ProposedFormula,
    *,
    analysis: AgreementAnalysis | None = None,
    known_variables: Iterable[str] = (),
    known_parameters: Iterable[str] = (),
    known_concepts: Iterable[str] = (),
    now: datetime | None = None,
) -> ProposedFormula:
    """Return a copy with a fresh report and a safe state transition.

    ``draft`` becomes ``validated`` only when the report has no errors. Invalid
    proposals stay in ``draft``. Approved/rejected records are never silently
    downgraded; the attached report still tells the reviewer the truth.
    """

    report = validate_formula_proposal(
        formula,
        analysis=analysis,
        known_variables=known_variables,
        known_parameters=known_parameters,
        known_concepts=known_concepts,
        now=now,
    )
    status = formula.status
    if status is ProposalStatus.DRAFT:
        status = ProposalStatus.VALIDATED if report.is_valid else ProposalStatus.DRAFT
    elif status is ProposalStatus.VALIDATED and not report.is_valid:
        status = ProposalStatus.DRAFT
    return formula.model_copy(update={"validation": report, "status": status})


def _validate_source(
    formula: ProposedFormula,
    analysis: AgreementAnalysis | None,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    source = formula.source
    if source.content_hash is None:
        errors.append(
            _issue(
                "missing_content_hash",
                "source.content_hash is required; it must be computed from the "
                "analyzed document, not supplied by the model",
                "source.content_hash",
            )
        )
    if source.page is None and not source.article:
        warnings.append(
            _issue(
                "source_not_specific",
                "source has neither page nor article; a human reviewer cannot locate "
                "the exact provision",
                "source",
            )
        )
    if analysis is not None:
        document = analysis.document
        if source.document_id != document.document_id:
            errors.append(
                _issue(
                    "source_document_mismatch",
                    f"source document_id {source.document_id!r} does not match the "
                    f"analyzed document {document.document_id!r}",
                    "source.document_id",
                )
            )
        if source.version != document.version:
            errors.append(
                _issue(
                    "source_version_mismatch",
                    f"source version {source.version!r} does not match the analyzed "
                    f"version {document.version!r}",
                    "source.version",
                )
            )
        if (
            document.content_hash
            and source.content_hash
            and source.content_hash != document.content_hash
        ):
            errors.append(
                _issue(
                    "source_hash_mismatch",
                    "source.content_hash does not match the analyzed document hash",
                    "source.content_hash",
                )
            )


class _References:
    def __init__(self) -> None:
        self.variables: set[str] = set()
        self.parameters: set[str] = set()
        self.concepts: set[str] = set()


def _validate_dsl_tree(tree: Any, errors: list[ValidationIssue]) -> _References:
    references = _References()
    _walk_node(tree, "formula", errors, references)
    return references


def _walk_node(
    node: Any,
    path: str,
    errors: list[ValidationIssue],
    references: _References,
) -> None:
    if isinstance(node, bool):
        errors.append(
            _issue(
                "invalid_node",
                f"DSL node at {path} cannot be a bare boolean",
                path,
            )
        )
        return
    if isinstance(node, (int, Decimal)):
        return
    if isinstance(node, float):
        errors.append(
            _issue(
                "invalid_constant",
                f"DSL node at {path} is a binary float; use a decimal string or "
                '{"constant": "..."}',
                path,
            )
        )
        return
    if not isinstance(node, dict):
        errors.append(
            _issue(
                "invalid_node",
                f"DSL node at {path} must be an object, got {type(node).__name__}",
                path,
            )
        )
        return

    unsafe = _UNSAFE_KEYS.intersection(node)
    if unsafe:
        errors.append(
            _issue(
                "unsafe_expression",
                f"DSL node at {path} contains forbidden executable key(s): "
                f"{', '.join(sorted(unsafe))}",
                path,
            )
        )
        return

    if "operator" not in node:
        _walk_leaf(node, path, errors, references)
        return

    operator = node.get("operator")
    if not isinstance(operator, str) or operator not in DSL_OPERATORS:
        errors.append(
            _issue(
                "unknown_operator",
                f"unknown DSL operator {operator!r} at {path}; allowed operators: "
                f"{', '.join(sorted(DSL_OPERATORS))}",
                path,
            )
        )
        return

    extra_keys = set(node) - _OPERATOR_KEYS
    if extra_keys:
        errors.append(
            _issue(
                "invalid_node",
                f"operator node at {path} has unsupported key(s): "
                f"{', '.join(sorted(extra_keys))}",
                path,
            )
        )
        return

    arguments = node.get("arguments")
    if not isinstance(arguments, list) or not arguments:
        errors.append(
            _issue(
                "missing_argument",
                f"operator {operator!r} at {path} requires a non-empty 'arguments' list",
                path,
            )
        )
        return

    expected = _ARITY_EXACT.get(operator)
    minimum = _ARITY_MIN.get(operator)
    if expected is not None and len(arguments) != expected:
        errors.append(
            _issue(
                "invalid_arity",
                f"operator {operator!r} at {path} expects {expected} arguments, got "
                f"{len(arguments)}",
                path,
            )
        )
    if minimum is not None and len(arguments) < minimum:
        errors.append(
            _issue(
                "invalid_arity",
                f"operator {operator!r} at {path} expects at least {minimum} "
                f"arguments, got {len(arguments)}",
                path,
            )
        )
    if operator == "round" and len(arguments) == 2:
        if not _is_rounding_decimals(arguments[1]):
            errors.append(
                _issue(
                    "invalid_rounding",
                    f"'round' node at {path} has invalid decimals {arguments[1]!r}; "
                    "expected an integer from 0 to 6 or a decimal string",
                    path,
                )
            )
    for index, argument in enumerate(arguments):
        _walk_node(argument, f"{path}.arguments[{index}]", errors, references)


def _is_rounding_decimals(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, dict):
        if set(value) == {"constant"}:
            return _is_rounding_decimals(value["constant"])
        return False
    if isinstance(value, int):
        return 0 <= value <= 6
    if isinstance(value, str) and value.strip().isdigit():
        return 0 <= int(value.strip()) <= 6
    return False


def _walk_leaf(
    node: dict[str, Any],
    path: str,
    errors: list[ValidationIssue],
    references: _References,
) -> None:
    keys = set(node)
    if len(keys) != 1:
        errors.append(
            _issue(
                "invalid_node",
                f"leaf node at {path} must contain exactly one of variable, parameter, "
                f"concept or constant; got {sorted(keys)}",
                path,
            )
        )
        return
    key = next(iter(keys))
    if key not in _LEAF_KEYS:
        errors.append(
            _issue(
                "invalid_node",
                f"leaf node at {path} uses unknown key {key!r}",
                path,
            )
        )
        return
    value = node[key]
    if key == "constant":
        parsed = _parse_constant(value)
        if parsed is None:
            errors.append(
                _issue(
                    "invalid_constant",
                    f"constant at {path} must be a finite number or numeric string, "
                    f"got {value!r}",
                    path,
                )
            )
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(
            _issue(
                "invalid_reference",
                f"{key} at {path} must be a non-blank string",
                path,
            )
        )
        return
    name = value.strip()
    if key == "variable":
        references.variables.add(name)
    elif key == "parameter":
        references.parameters.add(name)
    else:
        references.concepts.add(name)


def _parse_constant(value: Any) -> Decimal | None:
    if isinstance(value, bool) or isinstance(value, (dict, list, float)):
        # The engine rejects binary floats; use a decimal string instead.
        return None
    if isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None
    if isinstance(value, (int, float, Decimal)):
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None
    return None


def _validate_conditions(
    conditions: list[dict[str, Any]],
    references: _References,
    errors: list[ValidationIssue],
) -> None:
    for index, condition in enumerate(conditions):
        path = f"conditions[{index}]"
        if not isinstance(condition, dict):
            errors.append(_issue("invalid_condition", f"{path} must be an object", path))
            continue
        if "field" not in condition:
            # The engine also accepts full DSL expression conditions.
            _walk_node(condition, path, errors, references)
            continue

        unknown = set(condition) - {"field", "operator", "value"}
        if unknown:
            errors.append(
                _issue(
                    "invalid_condition",
                    f"{path} has unsupported key(s): {', '.join(sorted(unknown))}",
                    path,
                )
            )
        field = condition.get("field")
        operator = condition.get("operator")
        if not isinstance(field, str) or not field.strip():
            errors.append(
                _issue("invalid_condition", f"{path}.field must be a non-blank string", path)
            )
        else:
            references.variables.add(field.strip())
        if not isinstance(operator, str) or operator not in CONDITION_OPERATORS:
            errors.append(
                _issue(
                    "invalid_condition",
                    f"{path} has unknown condition operator {operator!r}; allowed: "
                    f"{', '.join(sorted(CONDITION_OPERATORS))}",
                    path,
                )
            )
        value = condition.get("value")
        if "value" not in condition:
            errors.append(
                _issue(
                    "invalid_condition",
                    f"{path} requires a 'value'",
                    path,
                )
            )
        elif isinstance(value, dict):
            _walk_node(value, f"{path}.value", errors, references)
        elif isinstance(value, float):
            errors.append(
                _issue(
                    "invalid_condition",
                    f"{path}.value is a binary float; use a decimal string",
                    path,
                )
            )
        elif isinstance(value, list):
            errors.append(
                _issue(
                    "invalid_condition",
                    f"{path}.value must be a literal or DSL expression, not a list",
                    path,
                )
            )


def _validate_variable_declarations(
    formula: ProposedFormula,
    references: _References,
    known_variables: set[str],
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    declared = set(formula.variables)
    if known_variables:
        for name in sorted((references.variables | declared) - known_variables):
            errors.append(
                _issue(
                    "unknown_variable",
                    f"variable {name!r} is not present in the supplied variable "
                    "catalog",
                    "variables",
                )
            )
    if not declared and references.variables:
        missing = ", ".join(sorted(references.variables))
        warnings.append(
            _issue(
                "variables_not_declared",
                f"formula references variables without declaring them: {missing}",
                "variables",
            )
        )
        return
    for name in sorted(references.variables - declared):
        errors.append(
            _issue(
                "undeclared_variable",
                f"formula uses variable {name!r} but does not declare it in 'variables'",
                "variables",
            )
        )
    for name in sorted(declared - references.variables):
        warnings.append(
            _issue(
                "unused_variable",
                f"formula declares variable {name!r} but never references it",
                "variables",
            )
        )


def _validate_dependencies(
    formula: ProposedFormula,
    analysis: AgreementAnalysis | None,
    analysis_formulas: dict[str, ProposedFormula],
    references: _References,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    known = set(analysis_formulas)
    known.add(formula.code)

    for dependency in formula.depends_on:
        if dependency == formula.code:
            errors.append(
                _issue(
                    "dependency_cycle",
                    f"formula {formula.code!r} cannot depend on itself",
                    "depends_on",
                )
            )
        elif dependency not in known:
            if analysis is not None:
                errors.append(
                    _issue(
                        "unknown_dependency",
                        f"dependency {dependency!r} is not a formula in the analyzed "
                        "document",
                        "depends_on",
                    )
                )
            else:
                warnings.append(
                    _issue(
                        "unknown_dependency",
                        f"dependency {dependency!r} is not present in the current "
                        "proposal set",
                        "depends_on",
                    )
                )

    if formula.code in references.concepts:
        errors.append(
            _issue(
                "dependency_cycle",
                f"formula {formula.code!r} references its own concept and would "
                "depend on itself",
                "formula",
            )
        )

    graph: dict[str, set[str]] = {}
    for code, item in analysis_formulas.items():
        graph[code] = {dep for dep in item.depends_on if dep in known and dep != code}
    graph[formula.code] = {
        dep for dep in formula.depends_on if dep in known and dep != formula.code
    }
    graph[formula.code].update(
        ref
        for ref in references.concepts
        if ref in known and ref != formula.code
    )

    for cycle in _find_cycles(graph):
        if formula.code in cycle:
            rendered = " -> ".join([*cycle, cycle[0]])
            errors.append(
                _issue(
                    "dependency_cycle",
                    f"circular dependency detected: {rendered}",
                    "depends_on",
                )
            )


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> None:
        if node in visiting:
            if node in stack:
                start = stack.index(node)
                cycle = stack[start:]
                signature = frozenset(cycle)
                if not any(frozenset(existing) == signature for existing in cycles):
                    cycles.append(list(cycle))
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for dependency in sorted(graph.get(node, ())):
            visit(dependency)
        stack.pop()
        visiting.discard(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return cycles


def _validate_parameter_and_concept_references(
    formula: ProposedFormula,
    analysis: AgreementAnalysis | None,
    references: _References,
    known_parameters: set[str],
    known_concepts: set[str],
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    parameter_catalog = set(known_parameters)
    concept_catalog = set(known_concepts)
    if analysis is not None:
        parameter_catalog.update(item.code for item in analysis.parameters)
        concept_catalog.update(item.code for item in analysis.concepts)
        concept_catalog.update(item.code for item in analysis.formulas)

    for name in sorted(references.parameters - parameter_catalog):
        issue = _issue(
            "unknown_parameter",
            f"formula references parameter {name!r} which is not declared in the "
            "analysis or in the supplied catalog",
            "formula",
        )
        if analysis is not None or known_parameters:
            errors.append(issue)
        else:
            warnings.append(issue)

    for name in sorted(references.concepts - concept_catalog):
        issue = _issue(
            "unknown_concept",
            f"formula references concept {name!r} which is not declared in the "
            "analysis or in the supplied catalog",
            "formula",
        )
        if analysis is not None or known_concepts:
            errors.append(issue)
        else:
            warnings.append(issue)


def _validate_dates(
    formula: ProposedFormula,
    analysis: AgreementAnalysis | None,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    valid_from: date = formula.effective_from
    valid_to = formula.effective_to
    if valid_to is not None and valid_to < valid_from:
        errors.append(
            _issue(
                "invalid_validity_period",
                "effective_to is earlier than effective_from",
                "effective_from",
            )
        )
    if analysis is not None:
        if analysis.effective_from and valid_from < analysis.effective_from:
            warnings.append(
                _issue(
                    "formula_before_agreement",
                    f"formula starts on {valid_from} before the agreement effective "
                    f"date {analysis.effective_from}",
                    "effective_from",
                )
            )
        if analysis.effective_to and valid_to and valid_to > analysis.effective_to:
            warnings.append(
                _issue(
                    "formula_after_agreement",
                    f"formula ends on {valid_to} after the agreement effective date "
                    f"{analysis.effective_to}",
                    "effective_to",
                )
            )


def _validate_tests(
    formula: ProposedFormula,
    references: _References,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    if not formula.tests:
        warnings.append(
            _issue(
                "missing_tests",
                "proposal has no suggested numeric tests; human review cannot rely on "
                "a worked example",
                "tests",
            )
        )
        return
    known_inputs = references.variables | references.parameters | references.concepts
    for index, test in enumerate(formula.tests):
        path = f"tests[{index}]"
        if test.period is not None:
            if test.period < formula.effective_from:
                warnings.append(
                    _issue(
                        "test_period_outside_validity",
                        f"{path} period {test.period} is before the formula start "
                        f"{formula.effective_from}",
                        path,
                    )
                )
            if formula.effective_to is not None and test.period > formula.effective_to:
                warnings.append(
                    _issue(
                        "test_period_outside_validity",
                        f"{path} period {test.period} is after the formula end "
                        f"{formula.effective_to}",
                        path,
                    )
                )
        for name in sorted(set(test.inputs) - known_inputs):
            warnings.append(
                _issue(
                    "test_unknown_input",
                    f"{path} supplies input {name!r} which the formula does not "
                    "reference",
                    path,
                )
            )
        if test.tolerance < 0:
            errors.append(
                _issue(
                    "invalid_test",
                    f"{path} tolerance cannot be negative",
                    path,
                )
            )


def _run_engine_validator(
    formula: ProposedFormula,
) -> tuple[list[ValidationIssue], list[str], str | None]:
    """Best-effort integration with the engine validator.

    The engine module is owned by another worker and may not exist yet. Any
    import/signature failure is reported as a limitation, never as a false
    validation failure. A successfully executed validator that reports errors
    does make the proposal invalid.
    """

    try:
        module = importlib.import_module("app.core.payroll_engine.validations")
    except Exception:
        return [], [_ENGINE_LIMITATION], None

    validator = getattr(module, "validate_formula", None)
    if validator is None:
        return [], [_ENGINE_LIMITATION], None

    try:
        result = validator(formula.to_formula_definition())
    except TypeError as exc:
        note = (
            "app.core.payroll_engine.validations.validate_formula was detected but "
            f"its signature is incompatible ({type(exc).__name__}: {exc}); structural "
            "validation remains the effective check."
        )
        return [], [note], None
    except Exception as exc:
        return [
            _issue(
                "engine_validation_failed",
                "the payroll engine validator raised "
                f"{type(exc).__name__}: {exc}",
            )
        ], [], "app.core.payroll_engine.validations.validate_formula"

    issues, unsupported = _normalize_engine_result(result)
    if unsupported is not None:
        note = (
            "app.core.payroll_engine.validations.validate_formula returned an "
            f"unsupported result ({unsupported}); structural validation remains "
            "the effective check."
        )
        return [], [note], None
    return issues, [], "app.core.payroll_engine.validations.validate_formula"


def _normalize_engine_result(
    result: Any,
) -> tuple[list[ValidationIssue], str | None]:
    if result is None:
        return [], None
    if isinstance(result, bool):
        if result:
            return [], None
        return [
            _issue(
                "engine_validation_failed",
                "the payroll engine validator rejected the formula",
            )
        ], None
    if isinstance(result, (list, tuple, set)):
        if (
            isinstance(result, tuple)
            and len(result) == 2
            and isinstance(result[0], bool)
        ):
            valid, raw_errors = result
            if valid:
                return [], None
            messages = [str(item) for item in raw_errors] if raw_errors else []
            detail = "; ".join(messages) if messages else "no detail supplied"
            return [
                _issue(
                    "engine_validation_failed",
                    f"the payroll engine validator rejected the formula: {detail}",
                )
            ], None
        messages = [str(item) for item in result if str(item).strip()]
        if messages:
            return [
                _issue(
                    "engine_validation_failed",
                    "engine validator reported: " + "; ".join(messages),
                )
            ], None
        return [], None
    if isinstance(result, dict):
        valid = result.get("is_valid", result.get("valid"))
        raw_errors = result.get("errors", [])
    else:
        valid = getattr(result, "is_valid", getattr(result, "valid", None))
        raw_errors = getattr(result, "errors", [])
        if valid is None and not raw_errors:
            return [], type(result).__name__

    if valid is True:
        return [], None
    if valid is False:
        messages = [str(item) for item in raw_errors] if raw_errors else []
        detail = "; ".join(messages) if messages else "no detail supplied"
        return [
            _issue(
                "engine_validation_failed",
                f"the payroll engine validator rejected the formula: {detail}",
            )
        ], None
    return [], "missing is_valid flag"
