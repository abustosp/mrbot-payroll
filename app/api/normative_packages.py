# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
"""Admin/editor API for validated CCT catalog packages.

The router exposes read operations to admins and editors.  ``POST /import``
modifies global normative data and is restricted to admins.  It is a dry run by
default: the caller must send ``"dry_run": false`` to persist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, page
from app.auth.dependencies import require_role
from app.config import get_settings
from app.core.normative.package_loader import PackageValidationError, load_cct_catalog
from app.database.models import AgreementCategory, CollectiveAgreement, SalaryScale, User
from app.database.session import get_db

REPO_ROOT = Path(__file__).resolve().parents[2]
NORMATIVE_CCT_DIR = get_settings().normative_cct_dir.resolve()

router = APIRouter(prefix="/normative-packages", tags=["normative-packages"])


class PackagePathError(ValueError):
    """Raised when a requested package path is outside the allowed directory."""


class NormativePackageImportInput(BaseModel):
    """JSON body for a package import.

    Exactly one of ``catalog`` (inline JSON) or ``path`` (a JSON file under
    ``normative/cct/``) must be supplied.  ``dry_run`` defaults to ``True`` so
    an accidental request cannot change normative data.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    catalog: dict[str, Any] | list[Any] | None = None
    path: str | None = Field(default=None, max_length=1000)
    dry_run: bool = True


def resolve_catalog_path(raw_path: str, *, allowed_dir: Path | None = None) -> Path:
    """Resolve ``raw_path`` to an existing JSON file inside the CCT directory.

    Both repository-relative paths (``normative/cct/catalog.json``) and paths
    relative to ``normative/cct/`` (``catalog.json``) are accepted.  Any path
    that resolves outside the allowed directory is rejected; ``resolve()`` also
    follows symlinks so a symlink cannot escape the directory.
    """

    allowed = (allowed_dir or NORMATIVE_CCT_DIR).resolve()
    text = str(raw_path).strip()
    if not text:
        raise PackagePathError("La ruta del paquete no puede estar vacía")

    requested = Path(text)
    if requested.is_absolute():
        candidates = [requested.resolve()]
    else:
        # ``Path.cwd()`` first so a package installed with the project at
        # ``/app`` accepts ``normative/cct/catalog.json``; ``REPO_ROOT`` covers
        # editable installs and ``allowed`` accepts bare ``catalog.json``.
        candidates = [
            (Path.cwd() / requested).resolve(),
            (REPO_ROOT / requested).resolve(),
            (allowed / requested).resolve(),
        ]

    inside_allowed = [candidate for candidate in candidates if candidate.is_relative_to(allowed)]
    if not inside_allowed:
        raise PackagePathError("La ruta debe estar dentro de normative/cct/")
    for candidate in inside_allowed:
        if candidate.suffix.lower() != ".json":
            raise PackagePathError("El paquete debe ser un archivo .json")
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No existe el paquete {text!r}")


@router.get("/ccts")
def list_normative_ccts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    """List loaded collective agreements with category and scale counts."""

    result = page(
        db,
        select(CollectiveAgreement).order_by(
            CollectiveAgreement.code, CollectiveAgreement.year
        ),
        limit,
        offset,
    )
    rows = list(result["items"])
    agreement_ids = [row.id for row in rows]
    category_counts: dict[int, int] = {}
    scale_counts: dict[int, int] = {}
    if agreement_ids:
        category_counts = dict(
            db.execute(
                select(AgreementCategory.agreement_id, func.count(AgreementCategory.id))
                .where(AgreementCategory.agreement_id.in_(agreement_ids))
                .group_by(AgreementCategory.agreement_id)
            ).all()
        )
        scale_counts = dict(
            db.execute(
                select(AgreementCategory.agreement_id, func.count(SalaryScale.id))
                .join(SalaryScale, SalaryScale.category_id == AgreementCategory.id)
                .where(AgreementCategory.agreement_id.in_(agreement_ids))
                .group_by(AgreementCategory.agreement_id)
            ).all()
        )
    result["items"] = [
        {
            "id": row.id,
            "code": row.code,
            "year": row.year,
            "name": row.name,
            "activity": row.activity,
            "scope": row.scope,
            "active": row.active,
            "category_count": category_counts.get(row.id, 0),
            "salary_scale_count": scale_counts.get(row.id, 0),
        }
        for row in rows
    ]
    return result


@router.post("/import")
def import_normative_package(
    payload: NormativePackageImportInput,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """Validate and optionally import a CCT catalog (dry run by default)."""

    if (payload.catalog is None) == (payload.path is None):
        raise HTTPException(
            status_code=422,
            detail="Debe indicar exactamente uno de 'catalog' o 'path'",
        )

    if payload.path is not None:
        try:
            package_path = resolve_catalog_path(payload.path)
        except PackagePathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Paquete no encontrado") from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Ruta de paquete inválida") from exc
        try:
            catalog = json.loads(package_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"JSON inválido: {exc.msg}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=422, detail="No se pudo leer el paquete") from exc
    else:
        catalog = payload.catalog

    if not isinstance(catalog, (dict, list)):
        raise HTTPException(status_code=422, detail="El catálogo debe ser un objeto o lista JSON")

    try:
        result = load_cct_catalog(db, catalog, dry_run=payload.dry_run)
    except PackageValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"message": "Catálogo inválido", "errors": list(exc.errors)},
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflicto con una clave única o referencia existente",
        ) from exc

    if not payload.dry_run:
        commit_or_conflict(db)
    return result.as_dict()
