"""Guards de borrado y enriquecimiento de snapshot (V2-06, V2-07, B-27).

V2-06: ninguna tabla referencia a ``salary_scales``; borrar una escala en
uso corrompe reliquidaciones en silencio. El guard bloquea el ``DELETE``
ORM cuando un contrato activo solapa su vigencia.

V2-07: ``employment_contracts`` solo es referenciado por
``employment_history`` (SET NULL); borrar el contrato activo deja al
empleado fuera del cálculo (canal B-17) en vez de fallar al borrar. El
guard exige borrado lógico (``active=false``, respetado por el cálculo)
antes del ``DELETE`` físico.

Ambos errores son ``ValueError`` para que un futuro endpoint los mapee a
409 con ``commit_or_conflict`` (el patrón ya usado en conceptos).

B-27: el snapshot por corrida (``Ruleset.rules``) solo sellaba fórmulas y
parámetros. Este módulo enriquece cada ``Ruleset`` nuevo con las escalas
y contratos vigentes del período, leídos del identity map de la sesión
(sin SQL extra en el camino caliente) para no romper el pin B-35 de
consultas constantes.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import event, func, or_, select, true
from sqlalchemy.orm import object_session


class ScaleInUseError(ValueError):
    """La escala está referenciada por un contrato activo vigente."""


class ContractInUseError(ValueError):
    """El contrato activo debe darse de baja lógica antes de borrarse."""


def _parse_period(rules: dict[str, Any]) -> date | None:
    raw = rules.get("period")
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _scale_row_to_snapshot(scale: Any) -> dict[str, Any]:
    return {
        "id": scale.id,
        "category_id": scale.category_id,
        "valid_from": scale.valid_from.isoformat(),
        "valid_to": scale.valid_to.isoformat() if scale.valid_to else None,
        "base_salary": str(scale.base_salary),
        "additional": str(scale.additional),
        "amount_type": scale.amount_type,
    }


def _contract_row_to_snapshot(contract: Any) -> dict[str, Any]:
    return {
        "id": contract.id,
        "employee_id": contract.employee_id,
        "company_id": contract.company_id,
        "category_id": contract.category_id,
        "agreement_id": contract.agreement_id,
        "valid_from": contract.valid_from.isoformat(),
        "valid_to": contract.valid_to.isoformat() if contract.valid_to else None,
        "active": contract.active,
    }


def is_scale_referenced(connection: Any, scale: Any) -> bool:
    """True si un contrato activo solapa la vigencia de la escala."""
    from app.database.models import EmploymentContract

    table = EmploymentContract.__table__
    overlap_from = (
        table.c.valid_from <= scale.valid_to if scale.valid_to is not None else true()
    )
    count = connection.execute(
        select(func.count())
        .select_from(table)
        .where(
            table.c.category_id == scale.category_id,
            table.c.active.is_(True),
            overlap_from,
            or_(table.c.valid_to.is_(None), table.c.valid_to >= scale.valid_from),
        )
    ).scalar()
    return bool(count)


def register_guards() -> None:
    """Registra los listeners de borrado y snapshot. Idempotente."""
    from app.database.models import EmploymentContract, Ruleset, SalaryScale

    if getattr(register_guards, "_done", False):
        return

    @event.listens_for(SalaryScale, "before_delete")
    def _guard_scale_delete(mapper: Any, connection: Any, target: Any) -> None:
        if is_scale_referenced(connection, target):
            raise ScaleInUseError(
                f"La escala {target.id} (categoría {target.category_id}) "
                "tiene contratos activos vigentes; desvinculadlos o "
                "dadlos de baja antes de borrarla (409 si fuera por API)."
            )

    @event.listens_for(EmploymentContract, "before_delete")
    def _guard_contract_delete(mapper: Any, connection: Any, target: Any) -> None:
        if target.active:
            raise ContractInUseError(
                f"El contrato {target.id} del empleado {target.employee_id} "
                "sigue activo; marcadlo active=false antes de borrarlo "
                "(el cálculo ya excluye inactivos; 409 si fuera por API)."
            )

    @event.listens_for(Ruleset, "before_insert")
    def _enrich_ruleset_snapshot(mapper: Any, connection: Any, target: Any) -> None:
        rules = target.rules
        if not isinstance(rules, dict) or "scales" in rules or "contracts" in rules:
            return
        period = _parse_period(rules)
        session = object_session(target)
        scales: list[dict[str, Any]] = []
        contracts: list[dict[str, Any]] = []
        candidates: list[Any] = []
        if session is not None:
            try:
                candidates = list(session.identity_map.values())
            except Exception:
                candidates = []
        for obj in candidates:
            if isinstance(obj, SalaryScale):
                if period is not None and (
                    obj.valid_from > period
                    or (obj.valid_to is not None and obj.valid_to < period)
                ):
                    continue
                scales.append(_scale_row_to_snapshot(obj))
            elif isinstance(obj, EmploymentContract):
                if not obj.active:
                    continue
                if period is not None and (
                    obj.valid_from > period
                    or (obj.valid_to is not None and obj.valid_to < period)
                ):
                    continue
                contracts.append(_contract_row_to_snapshot(obj))
        scales.sort(key=lambda entry: (entry["category_id"], entry["valid_from"]))
        contracts.sort(key=lambda entry: (entry["employee_id"], entry["valid_from"]))
        target.rules = {**rules, "scales": scales, "contracts": contracts}

    register_guards._done = True  # type: ignore[attr-defined]
