from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from caddsuite.application.legacy_import import plan_legacy_import


def test_docking_inventory_is_read_only_safe_and_content_identified(tmp_path: Path) -> None:
    source = tmp_path / "dock-project"
    source.mkdir()
    (source / "project.conf").write_text(
        "EXHAUSTIVENESS=16\nNCORES=$(touch SHOULD_NOT_EXIST)\nunknown=discarded\n",
        encoding="utf-8",
    )
    (source / "jobs.csv").write_text(
        "name,smiles,pdb_id,safe_id\nRC8,CCO,5NIU,RC8__5NIU\n", encoding="utf-8"
    )
    output = source / "poses"
    output.mkdir()
    pose = output / "RC8.pdbqt"
    pose.write_bytes(b"pose data")
    plan = plan_legacy_import(source, kind="docking")

    assert plan.completeness == "partial"
    assert plan.metadata["configuration"] == {
        "EXHAUSTIVENESS": "16",
        "NCORES": "$(touch SHOULD_NOT_EXIST)",
    }
    assert plan.metadata["jobs.csv"]["row_count"] == 1
    assert next(item for item in plan.files if item.relative_path == "poses/RC8.pdbqt").sha256 == (
        hashlib.sha256(b"pose data").hexdigest()
    )
    assert not (source / "SHOULD_NOT_EXIST").exists()
    assert plan.manifest_sha256 == plan_legacy_import(source, kind="docking").manifest_sha256


def test_md_inventory_captures_observed_versions_and_mdp_and_omits_trajectory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "md-project"
    gromacs = source / "gromacs"
    gromacs.mkdir(parents=True)
    (source / "project.conf").write_text("TARGET_NS=100\nNCORES=16\n", encoding="utf-8")
    (gromacs / "md_master.log").write_text(
        "GROMACS - gmx mdrun, 2026.3-conda_forge\n", encoding="utf-8"
    )
    (gromacs / "step5_1.mdp").write_text("dt = 0.002\nnsteps = 500000\n", encoding="utf-8")
    (gromacs / "topol.top").write_text("[ system ]\nlegacy system\n", encoding="utf-8")
    trajectory = gromacs / "combined_fit.xtc"
    trajectory.write_bytes(b"trajectory placeholder")
    (gromacs / "step5_1.gro").write_text("production coordinates", encoding="utf-8")
    (gromacs / "step3_input.gro").write_text("initial coordinates", encoding="utf-8")

    plan = plan_legacy_import(source, kind="md")
    assert plan.metadata["engine_versions"] == ["2026.3-conda_forge"]
    assert plan.metadata["mdp_observations"]["step5_1.mdp"] == {
        "dt": "0.002",
        "nsteps": "500000",
    }
    selected = {item.relative_path for item in plan.files}
    assert "gromacs/topol.top" in selected
    assert "gromacs/step3_input.gro" in selected
    omitted = {item.relative_path: item.reason for item in plan.omitted}
    assert "gromacs/combined_fit.xtc" in omitted
    assert "gromacs/step5_1.gro" in omitted
    assert "unsupported MD artifact" in omitted["gromacs/combined_fit.xtc"]


def test_import_plan_enforces_file_and_total_size_limits(tmp_path: Path) -> None:
    source = tmp_path / "dock-project"
    source.mkdir()
    (source / "project.conf").write_text("PH=7.4\n", encoding="utf-8")
    (source / "results.csv").write_text("name,score\n", encoding="utf-8")
    (source / "large.pdb").write_bytes(b"x" * 32)
    plan = plan_legacy_import(source, kind="docking", max_file_bytes=16)
    assert any(item.relative_path == "large.pdb" for item in plan.omitted)


def test_import_plan_rejects_incomplete_project_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"project\.conf"):
        plan_legacy_import(tmp_path, kind="docking")


def test_import_plan_skips_symlinks_that_escape_source_root(tmp_path: Path) -> None:
    source = tmp_path / "dock-project"
    source.mkdir()
    (source / "project.conf").write_text("PH=7.4\n", encoding="utf-8")
    (source / "jobs.csv").write_text("name,smiles,pdb_id,safe_id\n", encoding="utf-8")
    outside = tmp_path / "outside.pdb"
    outside.write_text("private", encoding="utf-8")
    (source / "escape.pdb").symlink_to(outside)
    plan = plan_legacy_import(source, kind="docking")
    assert "escape.pdb" not in {item.relative_path for item in plan.files}
    assert any("symlink" in item.reason for item in plan.omitted)
