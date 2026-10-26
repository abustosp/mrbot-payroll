"""Resolve the web data source registered on the current application."""

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
    """Return the configured repository or lazily create the demo store.

    Se guarda en ``app.state`` para que cada aplicacion (y cada test) tenga un
    dataset aislado y para que el coordinador pueda inyectar una fuente real
    sin tocar las rutas.
    """

    source = getattr(request.app.state, "payroll_data_source", None)
    if source is None:
        source = DemoDataStore()
        request.app.state.payroll_data_source = source
    return source


__all__ = ["PayrollDataSource", "get_data_source"]
