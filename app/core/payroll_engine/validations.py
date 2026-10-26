"""Static validation for formula trees and their available inputs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.payroll_engine.dependency_resolver import DependencyError, resolve_dependencies
from app.core.payroll_engine.formula_engine import (
    _ALIASES,
    _ARITY,
    _IDENTIFIER,
    _OPERATORS,
    FormulaError,
    _concept_dependencies,
    _normalize_condition,
)
from app.core.payroll_engine.rounding import to_decimal
from app.core.payroll_engine.types import FormulaContext, FormulaDefinition

_NUMERIC_OPERATORS = {
    "add", "subtract", "multiply", "divide", "percentage", "min", "max", "abs",
    "round", "floor", "ceil",
}
_COMPARISONS = {"eq", "ne", "gt", "gte", "lt", "lte"}


def _input_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    to_decimal(value)
    return "number"


def _validate_node(
    expression: Any,
    path: str,
    errors: list[str],
    context: FormulaContext | None,
) -> str:
    if isinstance(expression, bool):
        return "boolean"
    if isinstance(expression, (int, Decimal)):
        return "number"
    if isinstance(expression, float):
        errors.append(f"{path}: binary float is not allowed; use a decimal string")
        return "number"
    if not isinstance(expression, dict):
        errors.append(f"{path}: expected a formula object or exact numeric constant")
        return "unknown"

    if len(expression) == 1:
        key, payload = next(iter(expression.items()))
        if key == "constant":
            try:
                to_decimal(payload)
            except ValueError as exc:
                errors.append(f"{path}.constant: {exc}")
            return "number"
        if key in {"variable", "parameter", "concept"}:
            if not isinstance(payload, str) or not payload:
                errors.append(f"{path}: {key} name must be a non-empty string")
                return "unknown"
            if context is None:
                return "unknown"
            values = {
                "variable": context.variables,
                "parameter": context.parameters,
                "concept": context.concepts,
            }[key]
            if payload not in values:
                errors.append(f"{path}: missing {key} {payload!r}")
                return "unknown"
            try:
                return _input_kind(values[payload])
            except ValueError as exc:
                errors.append(f"{path}: invalid {key} {payload!r}: {exc}")
                return "unknown"
        errors.append(f"{path}: unknown formula node {key!r}")
        return "unknown"

    if "operator" in expression:
        if set(expression) != {"operator", "arguments"}:
            errors.append(f"{path}: operator node must contain only operator and arguments")
            return "unknown"
        name, arguments = expression["operator"], expression["arguments"]
        if not isinstance(name, str):
            errors.append(f"{path}: operator name must be a string")
            return "unknown"
        name = _ALIASES.get(name, name)
        if name not in _OPERATORS:
            errors.append(f"{path}: unknown operator {name!r}")
            if isinstance(arguments, list):
                for index, argument in enumerate(arguments):
                    _validate_node(argument, f"{path}.arguments[{index}]", errors, context)
            else:
                errors.append(f"{path}: operator arguments must be a list")
            return "unknown"
        if not isinstance(arguments, list):
            errors.append(f"{path}: operator arguments must be a list")
            return "unknown"
        minimum, maximum = _ARITY[name]
        if len(arguments) < minimum or (maximum is not None and len(arguments) > maximum):
            wanted = str(minimum) if minimum == maximum else (
                f"at least {minimum}" if maximum is None else f"{minimum} or {maximum}"
            )
            errors.append(f"{path}: operator {name!r} expects {wanted} argument(s), got {len(arguments)}")
        kinds = [
            _validate_node(argument, f"{path}.arguments[{index}]", errors, context)
            for index, argument in enumerate(arguments)
        ]
        if name in _NUMERIC_OPERATORS:
            for index, kind in enumerate(kinds):
                if kind not in {"number", "unknown"}:
                    errors.append(f"{path}.arguments[{index}]: {name} requires a number, got {kind}")
            if name == "round" and len(kinds) == 2 and kinds[1] not in {"number", "unknown"}:
                errors.append(f"{path}.arguments[1]: round decimal places must be a number")
            if name == "divide" and len(arguments) == 2:
                if arguments[1] == {"constant": 0} or arguments[1] == {"constant": "0"} or arguments[1] == 0:
                    errors.append(f"{path}: division by zero")
            return "number"
        if name in _COMPARISONS:
            if name in {"gt", "gte", "lt", "lte"}:
                for index, kind in enumerate(kinds):
                    if kind not in {"number", "unknown"}:
                        errors.append(f"{path}.arguments[{index}]: {name} requires a number, got {kind}")
            elif len(kinds) == 2 and all(kind != "unknown" for kind in kinds) and kinds[0] != kinds[1]:
                errors.append(f"{path}: {name} operands must have matching types, got {kinds[0]} and {kinds[1]}")
            return "boolean"
        if name in {"and", "or", "not"}:
            for index, kind in enumerate(kinds):
                if kind not in {"boolean", "unknown"}:
                    errors.append(f"{path}.arguments[{index}]: {name} requires a boolean, got {kind}")
            return "boolean"
        if name == "if":
            if kinds and kinds[0] not in {"boolean", "unknown"}:
                errors.append(f"{path}.arguments[0]: if condition must be boolean, got {kinds[0]}")
            if len(kinds) == 3 and kinds[1] != "unknown" and kinds[2] != "unknown" and kinds[1] != kinds[2]:
                errors.append(f"{path}: if branches must have matching types, got {kinds[1]} and {kinds[2]}")
            return kinds[1] if len(kinds) > 1 else "unknown"
        if name == "coalesce":
            known = {kind for kind in kinds if kind not in {"unknown", "null"}}
            if len(known) > 1:
                errors.append(f"{path}: coalesce arguments must have matching types")
            return next(iter(known), "unknown")

    if "function" in expression:
        if set(expression) != {"function", "arguments"}:
            errors.append(f"{path}: function node must contain only function and arguments")
            return "unknown"
        name, arguments = expression["function"], expression["arguments"]
        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
            errors.append(f"{path}: invalid function name {name!r}")
            return "unknown"
        if not isinstance(arguments, list):
            errors.append(f"{path}: function arguments must be a list")
            return "unknown"
        if name in _OPERATORS:
            return _validate_node({"operator": name, "arguments": arguments}, path, errors, context)
        if context is None or not callable(context.functions.get(name)):
            errors.append(f"{path}: unknown function {name!r}")
        kinds = [
            _validate_node(argument, f"{path}.arguments[{index}]", errors, context)
            for index, argument in enumerate(arguments)
        ]
        for index, kind in enumerate(kinds):
            if kind not in {"number", "unknown"}:
                errors.append(f"{path}.arguments[{index}]: function {name!r} requires a number, got {kind}")
        return "unknown"

    errors.append(f"{path}: expected exactly one formula node")
    return "unknown"


def validate_formula(
    definition: FormulaDefinition,
    context: FormulaContext | None = None,
    definitions: list[FormulaDefinition] | None = None,
) -> list[str]:
    """Return structural, input, type, and dependency errors without evaluating the tree."""
    errors: list[str] = []
    result_kind = _validate_node(definition.formula, "$formula", errors, context)
    if result_kind not in {"number", "unknown"}:
        errors.append(f"$formula: formula must produce a number, got {result_kind}")

    for index, raw_condition in enumerate(definition.conditions):
        try:
            condition = _normalize_condition(raw_condition)
        except (FormulaError, TypeError) as exc:
            errors.append(f"condition {index + 1}: {exc}")
            continue
        kind = _validate_node(condition, f"$conditions[{index}]", errors, context)
        if kind not in {"boolean", "unknown"}:
            errors.append(f"$conditions[{index}]: condition must produce a boolean, got {kind}")

    if definitions is not None:
        all_definitions = list(definitions)
        if not any(item.code == definition.code for item in all_definitions):
            all_definitions.append(definition)
        try:
            resolve_dependencies(all_definitions)
        except DependencyError as exc:
            errors.append(str(exc))
    else:
        self_dependencies = (
            set(definition.depends_on)
            | _concept_dependencies(definition.formula)
            | set().union(*(_concept_dependencies(condition) for condition in definition.conditions))
        )
        if definition.code in self_dependencies:
            errors.append(f"circular formula dependency: {definition.code} -> {definition.code}")
    return errors
