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


def _canonical(code: str) -> str:
    """Case-insensitive comparison key (B-32: the runtime aliases every code)."""

    return code.casefold()


def resolve_dependencies(definitions: list[FormulaDefinition]) -> list[str]:
    """Return formula codes in stable dependency-first order.

    Codes and dependencies match case-insensitively because the calculator
    exposes every concept under its exact, upper and lower spellings.  Two
    codes that only differ by case are rejected as duplicates.
    """
    by_canonical: dict[str, FormulaDefinition] = {}
    for definition in definitions:
        key = _canonical(definition.code)
        if key in by_canonical:
            raise DependencyError(
                f"duplicate formula code {definition.code!r} "
                f"(collides with {by_canonical[key].code!r} ignoring case)"
            )
        by_canonical[key] = definition

    # Dependencies are reported with the spelling the author wrote, while the
    # ordering below keeps the historical original-spelling alphabetical order.
    raw: dict[str, set[str]] = {
        definition.code: _dependencies(definition) for definition in by_canonical.values()
    }
    missing = [
        f"{code} -> {dependency}"
        for code in sorted(raw)
        for dependency in sorted(raw[code])
        if _canonical(dependency) not in by_canonical
    ]
    if missing:
        raise DependencyError("missing formula dependency: " + ", ".join(missing))

    graph = {
        code: {by_canonical[_canonical(dependency)].code for dependency in dependencies}
        for code, dependencies in raw.items()
    }

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
