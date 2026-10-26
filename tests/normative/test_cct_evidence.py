import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.normative.package_loader import load_cct_catalog
from app.database import Base

ROOT = Path(__file__).resolve().parents[2]
CCT_DIR = ROOT / "normative" / "cct"
CATALOG_PATH = CCT_DIR / "catalog.json"


def _catalog_scale(scale: dict, source: dict) -> dict:
    page = scale.get("source_page")
    table = scale.get("source_table")
    page_article = f"p. {page}" if page is not None else ""
    if table:
        page_article = f"{page_article} — {table}" if page_article else table

    item = {
        "categoria": scale["category_code"],
        "importe": scale["amount"],
        "moneda": scale["currency"],
        "vigencia_desde": scale["valid_from"],
        "vigencia_hasta": scale.get("valid_to"),
        "fuente": source["title"],
        "pagina_articulo": page_article,
        "estado": "verified",
        "source_id": scale["source_id"],
        "verification_source": source["source_url"],
    }
    if scale["valid_from"] < "2020-01-01":
        item["historical"] = True
    return item


def test_all_evidence_matches_verified_catalog_scales() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    evidence_dirs = sorted((CCT_DIR / "evidence").glob("cct_*"))
    assert len(catalog) == len(evidence_dirs) == 11
    ccts = {cct["code"]: cct for cct in catalog}
    assert len(ccts) == 11
    evidence_codes = {
        json.loads((evidence_dir / "sources.json").read_text(encoding="utf-8"))["cct"]
        for evidence_dir in evidence_dirs
    }
    assert evidence_codes == set(ccts)

    historical_scales = []
    for evidence_dir in evidence_dirs:
        sources = json.loads((evidence_dir / "sources.json").read_text(encoding="utf-8"))
        scale_data = json.loads((evidence_dir / "scales.json").read_text(encoding="utf-8"))
        cct = ccts[sources["cct"]]
        documents = sources["documents"]
        source_by_id = {source["id"]: source for source in documents}

        assert len(source_by_id) == len(documents), f"Duplicate source IDs in {evidence_dir}"
        assert cct["evidence_dir"] == str(evidence_dir.relative_to(ROOT))
        assert cct["evidence_documents"] == len(documents)
        assert cct["evidence_updated_at"] == sources["searched_at"]
        assert cct["evidence_note"]

        for source in documents:
            for field in ("published_at", "valid_from", "valid_to"):
                if source.get(field):
                    date.fromisoformat(source[field])
            if source.get("valid_from") and source.get("valid_to"):
                assert source["valid_from"] <= source["valid_to"], source["id"]
            assert re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", "")), source["id"]

            local_path = source.get("local_path")
            if not local_path:
                continue
            local_file = evidence_dir / local_path
            if not local_file.exists():
                # Raw evidence PDFs are intentionally not versioned due to size.
                assert source["content_type"] == "application/pdf", source["id"]
                continue

            data = local_file.read_bytes()
            assert hashlib.sha256(data).hexdigest() == source["sha256"], source["id"]
            if source["content_type"] == "application/pdf":
                assert data.startswith(b"%PDF-"), source["id"]
            else:
                assert source["content_type"] == "text/html", source["id"]

        evidence_scales = scale_data["scales"]
        verified_scales = [scale for scale in evidence_scales if scale["status"] == "verified"]
        category_codes = {category["code"].casefold() for category in cct["categories"]}
        keys = set()
        for scale in evidence_scales:
            assert scale["category_code"] and scale.get("category_name")
            start = date.fromisoformat(scale["valid_from"])
            end = date.fromisoformat(scale["valid_to"]) if scale.get("valid_to") else None
            assert end is None or start <= end, scale
            assert scale["source_id"] in source_by_id, scale
            assert scale["status"] in {"verified", "unverified"}, scale
            if scale["status"] != "verified":
                continue

            source = source_by_id[scale["source_id"]]
            assert source["official"] is True, source["id"]
            assert source.get("source_url", "").startswith(("http://", "https://")), source["id"]
            assert scale["category_code"].casefold() in category_codes, scale["category_code"]
            assert Decimal(str(scale["amount"])) > 0, scale
            assert scale["currency"]
            key = (scale["category_code"], scale["currency"], scale["valid_from"], scale.get("valid_to"))
            assert key not in keys, f"Duplicate verified scale in {evidence_dir}: {key}"
            keys.add(key)

        expected = [_catalog_scale(scale, source_by_id[scale["source_id"]]) for scale in verified_scales]
        assert cct["salary_scales"] == expected, f"Catalog/evidence mismatch for {sources['cct']}"
        assert cct["evidence_scales_verified"] == len(verified_scales)
        latest_from = max(scale["valid_from"] for scale in verified_scales)
        latest_to = max(
            (scale["valid_to"] for scale in verified_scales
             if scale["valid_from"] == latest_from and scale.get("valid_to")),
            default=None,
        )
        assert cct["latest_verified_from"] == latest_from
        assert cct["latest_verified_to"] == latest_to
        historical_scales.extend(
            scale for scale in cct["salary_scales"] if scale.get("historical") is True
        )

    assert len(historical_scales) == 8
    assert all(scale["vigencia_desde"].startswith("2007") for scale in historical_scales)


def test_real_loader_accepts_catalog_with_verified_scales_only(tmp_path: Path) -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as session:
        result = load_cct_catalog(session, catalog, dry_run=True)

    assert len(result.catalog_codes) == 11
    assert result.scales.created == sum(cct["evidence_scales_verified"] for cct in catalog)
    assert result.warnings == ()
