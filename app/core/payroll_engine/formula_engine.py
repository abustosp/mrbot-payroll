"""Safe interpreter for declarative payroll formula trees."""

from __future__ import annotations

import json
import re
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Decimal,
    DecimalException,
    localcontext,
)
from typing import Any, cast

from app.core.payroll_engine.rounding import quantize, to_decimal
from app.core.payroll_engine.types import (
    FormulaContext,
    FormulaDefinition,
    FormulaResult,
    RoundingMode,
    RoundingPolicy,
)


class FormulaError(ValueError):
    """Raised when a formula is malformed or cannot be evaluated."""


_ALIASES = {
    "greater_than": "gt",
    "greater_than_or_equal": "gte",
    "greater_than_or_equal_to": "gte",
    "less_than": "lt",
    "less_than_or_equal": "lte",
    "less_than_or_equal_to": "lte",
    "equal": "eq",
    "equals": "eq",
    "not_equal": "ne",
    "not_equals": "ne",
}
_OPERATORS = {
    "add", "subtract", "multiply", "divide", "percentage", "min", "max", "abs",
    "round", "floor", "ceil", "if", "eq", "ne", "gt", "gte", "lt", "lte",
    "and", "or", "not", "coalesce",
}
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_ARITY = {
    "add": (2, None),
    "subtract": (2, 2),
    "multiply": (2, None),
    "divide": (2, 2),
    "percentage": (2, 2),
    "min": (1, None),
    "max": (1, None),
    "abs": (1, 1),
    "round": (1, 2),
    "floor": (1, 1),
    "ceil": (1, 1),
    "if": (3, 3),
    "eq": (2, 2),
    "ne": (2, 2),
    "gt": (2, 2),
    "gte": (2, 2),
    "lt": (2, 2),
    "lte": (2, 2),
    "and": (2, None),
    "or": (2, None),
    "not": (1, 1),
    "coalesce": (1, None),
}


def _shown(value: Any) -> str:
    return str(value) if not isinstance(value, str) else repr(value)


def _numeric(value: Any, where: str) -> Decimal:
    try:
        return to_decimal(value)
    except ValueError as exc:
        raise FormulaError(f"{where} must be a finite decimal: {exc}") from exc


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise FormulaError(f"{where} must be boolean, got {type(value).__name__}")
    return value


def _check_arity(name: str, count: int) -> None:
    minimum, maximum = _ARITY[name]
    if count < minimum or (maximum is not None and count > maximum):
        expected = str(minimum) if minimum == maximum else (
            f"at least {minimum}" if maximum is None else f"{minimum} or {maximum}"
        )
        raise FormulaError(f"operator {name!r} expects {expected} argument(s), got {count}")


def _normalize_condition(condition: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(condition, dict):
        raise FormulaError("condition must be an expression object")
    if "field" not in condition:
        return condition
    if set(condition) != {"field", "operator", "value"}:
        raise FormulaError("condition with 'field' must contain exactly field, operator, and value")
    field = condition["field"]
    operator = condition["operator"]
    if not isinstance(field, str) or not field:
        raise FormulaError("condition field must be a non-empty variable name")
    if not isinstance(operator, str):
        raise FormulaError("condition operator must be a string")
    operator = _ALIASES.get(operator, operator)
    value = condition["value"]
    right = value if isinstance(value, dict) else {"constant": value}
    return {"operator": operator, "arguments": [{"variable": field}, right]}


def _expression_text(expression: Any) -> str:
    try:
        return json.dumps(expression, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(expression)


class _Evaluator:
    def __init__(self, context: FormulaContext) -> None:
        self.context = context
        self.trace: list[str] = []

    def evaluate(self, expression: Any, path: str = "$") -> Any:
        if isinstance(expression, bool):
            return expression
        if isinstance(expression, (Decimal, int)):
            return _numeric(expression, path)
        if isinstance(expression, float):
            return _numeric(expression, path)
        if not isinstance(expression, dict):
            raise FormulaError(f"{path}: expected a formula object or numeric constant")
        if len(expression) == 1:
            key, payload = next(iter(expression.items()))
            if key == "constant":
                result = _numeric(payload, f"{path}.constant")
                self.trace.append(f"Constant {result}")
                return result
            if key in ("variable", "parameter", "concept"):
                return self._reference(key, payload, path)
            raise FormulaError(f"{path}: unknown formula node {key!r}")
        if "operator" in expression:
            if set(expression) != {"operator", "arguments"}:
                raise FormulaError(f"{path}: operator node must contain only operator and arguments")
            name = expression["operator"]
            arguments = expression["arguments"]
            if not isinstance(name, str):
                raise FormulaError(f"{path}: operator name must be a string")
            name = _ALIASES.get(name, name)
            if name not in _OPERATORS:
                raise FormulaError(f"{path}: unknown operator {name!r}")
            if not isinstance(arguments, list):
                raise FormulaError(f"{path}: operator arguments must be a list")
            _check_arity(name, len(arguments))
            # Boolean operators and if only evaluate the branches needed for the result.
            operator_result: Any
            if name == "if":
                test = _boolean(self.evaluate(arguments[0], f"{path}.arguments[0]"), "if condition")
                operator_result = self.evaluate(arguments[1 if test else 2], f"{path}.arguments[{1 if test else 2}]")
            elif name == "and":
                operator_result = True
                for index, argument in enumerate(arguments):
                    if not _boolean(self.evaluate(argument, f"{path}.arguments[{index}]"), "and argument"):
                        operator_result = False
                        break
            elif name == "or":
                operator_result = False
                for index, argument in enumerate(arguments):
                    if _boolean(self.evaluate(argument, f"{path}.arguments[{index}]"), "or argument"):
                        operator_result = True
                        break
            elif name == "coalesce":
                operator_result = None
                for index, argument in enumerate(arguments):
                    operator_result = self.evaluate(argument, f"{path}.arguments[{index}]")
                    if operator_result is not None:
                        break
            else:
                values = [self.evaluate(arg, f"{path}.arguments[{index}]") for index, arg in enumerate(arguments)]
                operator_result = self._apply(name, values, path)
            self.trace.append(f"{name} = {_shown(operator_result)}")
            return operator_result
        if "function" in expression:
            if set(expression) != {"function", "arguments"}:
                raise FormulaError(f"{path}: function node must contain only function and arguments")
            name, arguments = expression["function"], expression["arguments"]
            if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
                raise FormulaError(f"{path}: invalid function name {name!r}")
            if not isinstance(arguments, list):
                raise FormulaError(f"{path}: function arguments must be a list")
            if name in _OPERATORS:
                result = self.evaluate({"operator": name, "arguments": arguments}, path)
                self.trace.append(f"function {name} = {_shown(result)}")
                return result
            else:
                function = self.context.functions.get(name)
                if not callable(function):
                    raise FormulaError(f"{path}: unknown function {name!r}; register it by name in FormulaContext.functions")
                values = [self.evaluate(arg, f"{path}.arguments[{index}]") for index, arg in enumerate(arguments)]
                numeric_values = [_numeric(value, f"argument to function {name!r}") for value in values]
                try:
                    result = function(*numeric_values)
                except Exception as exc:
                    raise FormulaError(f"function {name!r} failed: {exc}") from exc
                if result is not None and not isinstance(result, bool):
                    result = _numeric(result, f"result of function {name!r}")
            self.trace.append(f"function {name} = {_shown(result)}")
            return result
        raise FormulaError(f"{path}: expected one formula node")

    def _reference(self, kind: str, name: Any, path: str) -> Any:
        if not isinstance(name, str) or not name:
            raise FormulaError(f"{path}: {kind} name must be a non-empty string")
        values = {
            "variable": self.context.variables,
            "parameter": self.context.parameters,
            "concept": self.context.concepts,
        }[kind]
        if name not in values:
            raise FormulaError(f"{path}: missing {kind} {name!r}")
        value = values[name]
        if value is not None and not isinstance(value, bool):
            value = _numeric(value, f"{kind} {name!r}")
        self.trace.append(f"Input {kind} {name!r} = {_shown(value)}")
        return value

    def _apply(self, name: str, values: list[Any], path: str) -> Any:
        if name in {"add", "subtract", "multiply", "divide", "percentage", "min", "max", "abs", "round", "floor", "ceil"}:
            numbers = [_numeric(value, f"{name} operand") for value in values]
            digits = sum(len(number.as_tuple().digits) for number in numbers)
            alignment = 0
            if name in {"add", "subtract"}:
                integer_digits = max(1, max(number.adjusted() + 1 for number in numbers))
                scale = max(0, -cast(int, min(number.as_tuple().exponent for number in numbers)))
                alignment = integer_digits + scale + len(numbers) + 2
            with localcontext() as decimal_context:
                decimal_context.prec = max(50, digits + 20, alignment)
                decimal_context.rounding = ROUND_HALF_EVEN
                try:
                    if name == "add":
                        return sum(numbers, Decimal(0))
                    if name == "subtract":
                        return numbers[0] - numbers[1]
                    if name == "multiply":
                        result = numbers[0]
                        for number in numbers[1:]:
                            result *= number
                        return result
                    if name == "divide":
                        if numbers[1] == 0:
                            raise FormulaError(f"{path}: division by zero")
                        return numbers[0] / numbers[1]
                    if name == "percentage":
                        # DSL percentage(a, b) is defined as a * b / 100.
                        return numbers[0] * numbers[1] / Decimal(100)
                    if name == "min":
                        return min(numbers)
                    if name == "max":
                        return max(numbers)
                    if name == "abs":
                        return abs(numbers[0])
                    if name == "round":
                        places = 0 if len(numbers) == 1 else _decimal_places(numbers[1], path)
                        return quantize(numbers[0], RoundingPolicy(decimals=places, mode=RoundingMode.HALF_UP))
                    if name == "floor":
                        return numbers[0].to_integral_value(rounding=ROUND_FLOOR)
                    if name == "ceil":
                        return numbers[0].to_integral_value(rounding=ROUND_CEILING)
                except DecimalException as exc:
                    raise FormulaError(f"{path}: decimal operation {name!r} failed: {exc}") from exc
        if name in {"eq", "ne"}:
            left, right = values
            if isinstance(left, bool) or isinstance(right, bool):
                if not isinstance(left, bool) or not isinstance(right, bool):
                    raise FormulaError(f"{path}: {name} operands must have matching types")
            else:
                left, right = _numeric(left, f"{name} operand"), _numeric(right, f"{name} operand")
            return left == right if name == "eq" else left != right
        if name in {"gt", "gte", "lt", "lte"}:
            left, right = (_numeric(value, f"{name} operand") for value in values)
            return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[name]
        if name == "not":
            return not _boolean(values[0], "not argument")
        raise FormulaError(f"{path}: unsupported operator {name!r}")


def _decimal_places(value: Decimal, path: str) -> int:
    integral = value.to_integral_value()
    if value != integral:
        raise FormulaError(f"{path}: round decimal places must be an integer")
    places = int(integral)
    if not 0 <= places <= 6:
        raise FormulaError(f"{path}: round decimal places must be between 0 and 6")
    return places


def _concept_dependencies(expression: Any) -> set[str]:
    dependencies: set[str] = set()
    if isinstance(expression, dict):
        if set(expression) == {"concept"} and isinstance(expression["concept"], str):
            dependencies.add(expression["concept"])
        for value in expression.values():
            dependencies.update(_concept_dependencies(value))
    elif isinstance(expression, list):
        for value in expression:
            dependencies.update(_concept_dependencies(value))
    return dependencies


def evaluate_expression(expression: dict, context: FormulaContext) -> FormulaResult:
    """Evaluate one DSL tree without applying a formula-level rounding policy."""
    evaluator = _Evaluator(context)
    evaluator.trace.append(f"Expression: {_expression_text(expression)}")
    result = evaluator.evaluate(expression)
    value = _numeric(result, "formula result")
    evaluator.trace.append(f"Result: {value}")
    return FormulaResult(value=value, trace=evaluator.trace, dependencies=_concept_dependencies(expression))


def evaluate_formula(definition: FormulaDefinition, context: FormulaContext) -> FormulaResult:
    """Evaluate conditions and formula, then apply the definition's rounding policy."""
    evaluator = _Evaluator(context)
    evaluator.trace.append(f"Formula {definition.code}: {_expression_text(definition.formula)}")
    dependencies = set(definition.depends_on) | _concept_dependencies(definition.formula)
    for raw_condition in definition.conditions:
        dependencies.update(_concept_dependencies(raw_condition))
    for index, raw_condition in enumerate(definition.conditions):
        try:
            condition = _normalize_condition(raw_condition)
        except FormulaError as exc:
            raise FormulaError(f"condition {index + 1}: {exc}") from exc
        condition_met = _boolean(
            evaluator.evaluate(condition, f"condition[{index}]"), f"condition {index + 1}"
        )
        evaluator.trace.append(f"Condition {index + 1}: {'met' if condition_met else 'not met'}")
        if not condition_met:
            result = quantize(Decimal(0), definition.rounding)
            evaluator.trace.append(f"Result: {result} (conditions not met)")
            return FormulaResult(
                value=result,
                trace=evaluator.trace,
                dependencies=dependencies,
                conditions_met=False,
            )
    raw_value = evaluator.evaluate(definition.formula)
    value = _numeric(raw_value, "formula result")
    result = quantize(value, definition.rounding)
    evaluator.trace.append(f"Unrounded result: {value}")
    evaluator.trace.append(f"Rounded result ({definition.rounding.mode}, {definition.rounding.decimals} places): {result}")
    return FormulaResult(value=result, trace=evaluator.trace, dependencies=dependencies)
