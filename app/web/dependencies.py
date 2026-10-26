"""Resolve the web data source registered on the current application.

The application-level source is intentionally organization-agnostic.  Protected
routes derive the organization from the authenticated user, obtain the base
source from :func:`get_data_source` and build a request-scoped copy with
:func:`scope_data_source`.  The copy is stored on ``request.state`` so helpers
such as the template renderer reuse exactly the same scoped source instead of
falling back to the unscoped one.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import Request

from app.web.demo_data import DemoDataStore


class PayrollDataSource(Protocol):
    """Contrato de lectura que debe cumplir una fuente de datos real."""

    source_name: str
    is_demo: bool
    explanation: str


def get_data_source(request: Request) -> Any:
    """Return the request-scoped repository or the configured base source.

    Se guarda la fuente base en ``app.state`` para que cada aplicacion (y cada
    test) tenga un dataset aislado.  Las rutas protegidas guardan antes en
    ``request.state`` una copia acotada por organizacion; este helper devuelve
    esa copia para que el renderizado use exactamente la misma fuente.
    """

    scoped = getattr(request.state, "payroll_data_source", None)
    if scoped is not None:
        return scoped

    source = getattr(request.app.state, "payroll_data_source", None)
    if source is None:
        source = DemoDataStore()
        request.app.state.payroll_data_source = source
    return source


def scope_data_source(source: Any, organization_id: int) -> Any:
    """Return a copy of ``source`` restricted to ``organization_id``.

    Demo sources are shared in memory and must remain unchanged.  Real sources
    expose ``for_organization``; a source without that method is returned as-is
    so dependency overrides keep working, but the SQL source itself always
    applies its own organization filter.
    """

    if getattr(source, "is_demo", False):
        return source
    scope_factory = getattr(source, "for_organization", None)
    return scope_factory(organization_id) if callable(scope_factory) else source


__all__ = ["PayrollDataSource", "get_data_source", "scope_data_source"]
