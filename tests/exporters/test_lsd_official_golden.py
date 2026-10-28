"""The official spreadsheet results remain verifiable without network or office."""
import json
from pathlib import Path

import pytest

from app.exporters.txt.lsd import ENCODING, generate_concepts_file, generate_file, render_record
from scripts import verify_lsd_official

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/lsd_official_golden.json'


def test_official_golden_records_and_file_bytes() -> None:
    cases = json.loads(FIXTURE.read_text())['cases']
    assert {case['record_type'] for case in cases} == {'01', '02', '03', '04', '05', '06', 'concept'}
    for case in cases:
        assert render_record(case['record_type'], case['values']) == case['expected']
    liquidations = [case for case in cases if case['record_type'] != 'concept']
    records = [{'type': case['record_type'], **case['values']} for case in liquidations]
    expected = ('\r\n'.join(case['expected'] for case in liquidations) + '\r\n').encode(ENCODING)
    assert generate_file(records) == expected
    concept = next(case for case in cases if case['record_type'] == 'concept')
    assert generate_concepts_file([concept['values']]) == (concept['expected'] + '\r\n').encode(ENCODING)
    adjustment = next(case for case in cases if case['record_type'] == '03')
    adjusted = render_record('03', {**adjustment['values'], 'adjustment_period': '202605'})
    assert len(adjusted) == 51 and adjusted[-6:] == '202605'


def test_official_source_hash_mismatch_stops_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'documents': [{'id': 'test', 'source_url': 'https://example.org/file.pdf', 'sha256': '0' * 64}]}))
    (tmp_path / 'file.pdf').write_bytes(b'changed')
    monkeypatch.setattr(verify_lsd_official, 'CATALOG', path)
    with pytest.raises(ValueError, match='SHA-256 no coincide'):
        verify_lsd_official.sources(tmp_path)
