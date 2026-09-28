from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "benchmarks/redocking/pilot_v1/manifest.json"


def test_redocking_pilot_manifest_pins_eligible_source_inputs() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    assert manifest["schema"] == "caddsuite.redocking-benchmark/1"
    assert manifest["status"] == "executed_with_upstream_failures"
    execution = manifest["execution"]
    summary = (MANIFEST_PATH.parent / execution["summary_path"]).resolve(strict=True)
    assert not summary.is_symlink()
    assert hashlib.sha256(summary.read_bytes()).hexdigest() == execution["summary_sha256"]
    run = json.loads(summary.read_text(encoding="utf-8"))
    assert run["dataset_id"] == manifest["dataset_id"]
    assert run["case_count"] == 3
    assert run["successes"] == execution["primary_pose_recovery_success_count"] == 0
    assert sum(case["status"] == "succeeded" for case in run["cases"]) == 1
    assert set(execution["end_to_end_failed_case_ids"]) == {
        case["case_id"] for case in run["cases"] if case["status"] == "failed"
    }
    assert len(cases) == 3
    assert len({case["case_id"] for case in cases}) == len(cases)

    for case in cases:
        assert case["method"] == "X-RAY DIFFRACTION"
        assert case["resolution_angstrom"] <= manifest["selection"]["resolution_angstrom_max"]
        ligand = case["ligand"]
        assert (
            manifest["selection"]["heavy_atom_count_min"]
            <= ligand["heavy_atom_count"]
            <= manifest["selection"]["heavy_atom_count_max"]
        )
        references = [
            (case["structure_path"], case["structure_sha256"]),
            (ligand["ideal_graph_path"], ligand["ideal_graph_sha256"]),
        ]
        if "native_coordinates_path" in ligand:
            references.append(
                (ligand["native_coordinates_path"], ligand["native_coordinates_sha256"])
            )
        for relative_path, expected_hash in references:
            source = (MANIFEST_PATH.parent / relative_path).resolve(strict=True)
            assert not source.is_symlink()
            assert hashlib.sha256(source.read_bytes()).hexdigest() == expected_hash
