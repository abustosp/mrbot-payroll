"""Deterministic topological ordering for formula definitions."""

from __future__ import annotations

import heapq

from app.core.payroll_engine.formula_engine import _concept_dependencies
from app.core.payroll_engine.types import FormulaDefinition


class DependencyError(ValueError):
    """Raised for missing formula dependencies or dependency cycles."""


def _dependencies(definition: FormulaDefinition) -> set[str]:
    result = set(definition.depends_on)
    result.update(_concept_dependencies(definition.formula))
    for condition in definition.conditions:
        result.update(_concept_dependencies(condition))
    return result


def _find_cycle(graph: dict[str, set[str]]) -> list[str]:
    visiting: list[str] = []
    active: set[str] = set()
    visited: set[str] = set()

    def visit(code: str) -> list[str] | None:
        if code in active:
            start = visiting.index(code)
            return visiting[start:] + [code]
        if code in visited:
            return None
        active.add(code)
        visiting.append(code)
        for dependency in sorted(graph[code]):
            cycle = visit(dependency)
            if cycle:
                return cycle
        visiting.pop()
        active.remove(code)
        visited.add(code)
        return None

    for code in sorted(graph):
        cycle = visit(code)
        if cycle:
            return cycle
    return []


def resolve_dependencies(definitions: list[FormulaDefinition]) -> list[str]:
    """Return formula codes in stable dependency-first order."""
    by_code: dict[str, FormulaDefinition] = {}
    for definition in definitions:
        if definition.code in by_code:
            raise DependencyError(f"duplicate formula code {definition.code!r}")
        by_code[definition.code] = definition

    graph = {code: _dependencies(definition) for code, definition in by_code.items()}
    missing = [
        f"{code} -> {dependency}"
        for code in sorted(graph)
        for dependency in sorted(graph[code] - by_code.keys())
    ]
    if missing:
        raise DependencyError("missing formula dependency: " + ", ".join(missing))

    dependents: dict[str, set[str]] = {code: set() for code in graph}
    remaining = {code: set(dependencies) for code, dependencies in graph.items()}
    for code, dependencies in graph.items():
        for dependency in dependencies:
            dependents[dependency].add(code)

    ready = [code for code, dependencies in remaining.items() if not dependencies]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        code = heapq.heappop(ready)
        ordered.append(code)
        for dependent in sorted(dependents[code]):
            remaining[dependent].remove(code)
            if not remaining[dependent]:
                heapq.heappush(ready, dependent)

    if len(ordered) != len(graph):
        cycle = _find_cycle(graph)
        raise DependencyError("circular formula dependency: " + " -> ".join(cycle))
    return ordered
