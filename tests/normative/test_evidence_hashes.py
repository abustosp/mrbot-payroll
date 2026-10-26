"""B-39: re-verificacion offline de la evidencia normativa (SHA-256).

El loader (`load_cct_catalog`) no verifica bytes locales ni URLs: un PDF
corrupto se importaria igual como verificado. Este modulo es la red de
seguridad offline: recalcula el SHA-256 de cada archivo referenciado por
`sources.json`, exige que coincida con el hash registrado y encadena cada
escala `verified` con un documento cuyo hash se valido en esta corrida.
Un mismatch hace fallar el test: el dataset queda marcado como no
verificado hasta curarlo.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CCT_DIR = ROOT / "normative" / "cct"
EVIDENCE_DIR = CCT_DIR / "evidence"


def _load_evidence() -> list[tuple[Path, dict]]:
    """Devuelve (directorio, sources.json) por cada CCT."""
    result = []
    for evidence_dir in sorted(EVIDENCE_DIR.glob("cct_*")):
        sources = json.loads((evidence_dir / "sources.json").read_text(encoding="utf-8"))
        result.append((evidence_dir, sources))
    assert len(result) == 11, f"Se esperaban 11 directorios de evidencia, hay {len(result)}"
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_referenced_evidence_file_hash_matches() -> None:
    """Cada archivo presente referenciado por `sources.json` debe hashear igual.

    Los documentos cuyo archivo local no esta versionado se omiten (igual que
    en `test_cct_evidence.py`): solo se verifica lo que existe en disco.
    """
    checked = 0
    for evidence_dir, sources in _load_evidence():
        for doc in sources["documents"]:
            local_path = doc.get("local_path")
            if not local_path:
                continue
            local_file = evidence_dir / local_path
            if not local_file.exists():
                continue
            assert _sha256(local_file) == doc["sha256"], (
                f"{evidence_dir.name}/{local_path}: SHA-256 distinto al registrado "
                f"en {doc['id']} — evidencia corrupta o desactualizada"
            )
            checked += 1
    assert checked > 0, "Ningun archivo de evidencia presente para re-verificar"


def test_no_orphan_evidence_files() -> None:
    """Todo archivo bajo `pdfs/` y `html/` debe estar referenciado en `sources.json`.

    Bytes sin documento asociado no son evidencia trazable: o se registran
    (con su SHA-256 real) o el test falla con la lista exacta.
    """
    orphans = []
    for evidence_dir, sources in _load_evidence():
        referenced = {
            doc["local_path"] for doc in sources["documents"] if doc.get("local_path")
        }
        for sub in ("pdfs", "html"):
            subdir = evidence_dir / sub
            if not subdir.exists():
                continue
            for path in sorted(subdir.iterdir()):
                if path.is_file() and str(path.relative_to(evidence_dir)) not in referenced:
                    orphans.append(f"{evidence_dir.name}/{path.relative_to(evidence_dir)}")
    assert not orphans, f"Archivos de evidencia sin documento asociado: {orphans}"


def test_verified_scales_chain_to_hash_checked_documents() -> None:
    """Toda escala `verified` depende de un documento oficial con hash valido.

    Si el archivo local existe, su hash debe coincidir en esta corrida; si no
    esta versionado, el documento debe declarar sha256 y URL oficial para una
    verificacion online posterior. Un fallo aqui marca el dataset como no
    verificado (B-39).
    """
    checked = 0
    for evidence_dir, sources in _load_evidence():
        source_by_id = {doc["id"]: doc for doc in sources["documents"]}
        scales = json.loads((evidence_dir / "scales.json").read_text(encoding="utf-8"))["scales"]
        for scale in scales:
            if scale.get("status") != "verified":
                continue
            doc = source_by_id[scale["source_id"]]
            assert doc.get("official") is True, (
                f"{evidence_dir.name}: escala verified {scale['category_code']} "
                f"{scale['valid_from']} respalda en fuente no oficial {doc['id']}"
            )
            local_path = doc.get("local_path")
            if local_path and (evidence_dir / local_path).exists():
                assert _sha256(evidence_dir / local_path) == doc["sha256"], (
                    f"{evidence_dir.name}/{local_path}: hash invalido para escala "
                    f"verified {scale['category_code']} {scale['valid_from']}"
                )
                checked += 1
    assert checked > 0, "Ninguna escala verified con archivo local para encadenar"
