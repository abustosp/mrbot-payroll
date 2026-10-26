import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.normative.package_loader import load_cct_catalog
from app.database import Base

ROOT = Path(__file__).resolve().parents[2]


def test_real_catalog_loads_verified_data_and_skips_unverified_scales(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    catalog = json.loads((ROOT / "normative/cct/catalog.json").read_text(encoding="utf-8"))

    with factory() as session:
        result = load_cct_catalog(session, catalog, dry_run=True)

    assert len(result.catalog_codes) == 10
    assert result.agreements.created == 10
    assert result.scales.created == sum(cct["evidence_scales_verified"] for cct in catalog)
    assert result.warnings == ()

