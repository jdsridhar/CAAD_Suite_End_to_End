from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from benchmarks.redocking import curate_candidates as curate
from benchmarks.redocking import select_redocking_cohort as selection

FIXTURE = Path(__file__).parents[1] / "fixtures" / "redocking" / "6E5F.cif.gz"


def _catalog(path: Path) -> Path:
    value: dict[str, Any] = {
        "grouping": {"draw_seed": 20260929},
        "captured_entity_count": 4,
        "reported_entity_count": 4,
        "captured_at_utc": "2026-09-29T00:00:00+00:00",
        "query_sha256": "test-query-hash",
        "cluster_source": "fixture://cluster",
        "cluster_file": {
            "source_sha256": "test-cluster-source",
            "stored_sha256": "test-cluster-stored",
        },
        "groups_seeded": [
            {"cluster_id": "6E5D_1", "candidate_entity_ids_seeded": ["6E5F_1"]},
            {"cluster_id": "8GJW_1", "candidate_entity_ids_seeded": ["8GJW_1"]},
        ],
        "uncategorized_entities": [{"entity_id": "9ZZZ_1"}],
        "pilot_excluded_entities": [{"entity_id": "1M17_1"}],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_cohort_selection_records_every_candidate_and_resume_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compressed = FIXTURE.read_bytes()
    monkeypatch.setattr(
        selection,
        "_download_structure",
        lambda pdb_id: (compressed, {"url": f"fixture://{pdb_id}"}),
    )
    catalog = _catalog(tmp_path / "catalog.json")
    out = tmp_path / "cohort"
    manifest_path = selection.select_cohort(catalog, out, cohort_size=1)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["cohort_frozen"] is True
    assert manifest["cases"][0]["entity_id"] == "6E5F_1"
    assert manifest["cases"][0]["ligand"]["component_id"] == "L6T"
    decisions = [
        json.loads(line)
        for line in (out / "candidate_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(decisions) == 4
    assert {row["entity_id"] for row in decisions} == {"6E5F_1", "8GJW_1", "9ZZZ_1", "1M17_1"}
    assert (
        next(row for row in decisions if row["entity_id"] == "8GJW_1")["status"]
        == "not_assessed_cohort_complete"
    )
    resumed = selection.select_cohort(catalog, out, cohort_size=1, resume=True)
    resumed_manifest = json.loads(resumed.read_text(encoding="utf-8"))
    assert resumed_manifest["cases"] == manifest["cases"]
    assert resumed_manifest["candidate_decisions_sha256"] == manifest["candidate_decisions_sha256"]


def test_resume_rejects_changed_selection_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compressed = FIXTURE.read_bytes()
    monkeypatch.setattr(selection, "_download_structure", lambda _: (compressed, {}))
    catalog = _catalog(tmp_path / "catalog.json")
    out = tmp_path / "cohort"
    selection.select_cohort(catalog, out, cohort_size=1)
    with pytest.raises(ValueError, match="resume inputs"):
        selection.select_cohort(catalog, out, cohort_size=2, resume=True)


def test_selection_recovers_if_candidate_record_was_fsynced_before_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compressed = FIXTURE.read_bytes()
    monkeypatch.setattr(selection, "_download_structure", lambda _: (compressed, {}))
    catalog = _catalog(tmp_path / "catalog.json")
    out = tmp_path / "cohort"
    write_state = selection._atomic_json
    calls = 0

    def fail_after_decision(path: Path, value: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated supervisor interruption")
        write_state(path, value)

    monkeypatch.setattr(selection, "_atomic_json", fail_after_decision)
    with pytest.raises(OSError, match="simulated supervisor interruption"):
        selection.select_cohort(catalog, out, cohort_size=1)
    monkeypatch.setattr(selection, "_atomic_json", write_state)
    result = selection.select_cohort(catalog, out, cohort_size=1, resume=True)
    manifest = json.loads(result.read_text(encoding="utf-8"))
    assert manifest["selected_case_count"] == 1
    assert manifest["cases"][0]["entity_id"] == "6E5F_1"
    rows = (out / "candidate_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert sum(json.loads(row)["entity_id"] == "6E5F_1" for row in rows) == 1


def test_real_rcsb_structure_passes_locked_eligibility() -> None:
    result = curate.evaluate_cif(gzip.decompress(FIXTURE.read_bytes()), "1")
    assert result["entry_id"] == "6E5F"
    assert result["eligible"] is True
    ligand = result["ligand_instances"][0]
    assert ligand["ligand"]["component_id"] == "L6T"
    assert ligand["ligand"]["heavy_atom_count"] == 35
    assert ligand["ligand"]["observed_atoms"] == 35
    assert ligand["ligand"]["nearest_target_atom_A"] < 4.0
    assert ligand["ligand"]["protein_altloc_policy"]
    assert ligand["ligand"]["selected_ligand_atom_altlocs"]


def test_structure_over_resolution_cutoff_is_rejected() -> None:
    import re

    cif = re.sub(
        rb"(_refine\.ls_d_res_high\s+)1\.37\b",
        rb"\g<1>2.51",
        gzip.decompress(FIXTURE.read_bytes()),
        count=1,
    )
    result = curate.evaluate_cif(cif, "1")
    assert result["eligible"] is False
    assert any("resolution does not meet" in reason for reason in result["reasons"])
    assert result["ligand_instances"][0]["eligible"] is False


def test_target_entity_must_exist_in_entry() -> None:
    result = curate.evaluate_cif(gzip.decompress(FIXTURE.read_bytes()), "999")
    assert result["eligible"] is False
    assert result["reasons"] == ["target polymer entity not present in mmCIF"]


def test_equal_occupancy_ligand_alternates_are_rejected() -> None:
    atom = {
        "label_asym_id": "B",
        "label_seq_id": "301",
        "label_comp_id": "LIG",
        "type_symbol": "C",
        "label_atom_id": "C1",
    }
    rows = [{**atom, "label_alt_id": alt, "occupancy": "0.5"} for alt in ("A", "B")]
    selected, issues = curate._ligand_atoms(rows, ("B", "301", "LIG"))
    assert selected == []
    assert issues == ["equal-occupancy ligand alternate locations for atom C1"]


def test_low_occupancy_ligand_atom_is_rejected() -> None:
    atom = {
        "label_asym_id": "B",
        "label_seq_id": "301",
        "label_comp_id": "LIG",
        "type_symbol": "C",
        "label_atom_id": "C1",
        "label_alt_id": "A",
        "occupancy": "0.79",
    }
    selected, issues = curate._ligand_atoms([atom], ("B", "301", "LIG"))
    assert len(selected) == 1
    assert issues == ["ligand atom C1 occupancy below 0.80"]


def test_capture_fixture_hash_is_stable() -> None:
    import hashlib

    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == (
        "0e70cb1e299178285e15e888731ed0de3f5397f32bc193a380becde1bfb6cfb4"
    )
    assert len(gzip.decompress(FIXTURE.read_bytes())) > 100_000
