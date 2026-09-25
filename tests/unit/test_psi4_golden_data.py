from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/data/golden/qm"


def test_legacy_batch_golden_files_match_manifest_hashes() -> None:
    manifest = json.loads((GOLDEN / "batch_series_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["entries"]) == {"ethanol", "acetic_acid", "aspirin", "benzene"}
    for molecule, entry in manifest["entries"].items():
        fixture = GOLDEN / entry["fixture"]
        assert fixture.is_file(), molecule
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == entry["fixture_sha256"]
        assert len(entry["sha256"]) == 64
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        assert payload["functional"] == manifest["method"]
        assert payload["basis"] == manifest["basis"]
        assert payload["charge"] == 0
        assert payload["multiplicity"] == 1
        assert payload["reference"]["energy_hartree"] < 0
