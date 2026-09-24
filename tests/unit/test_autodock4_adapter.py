"""AutoDock4 planner and DLG parser tests use synthetic format fixtures only."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from caddsuite.adapters.docking.autodock4 import (
    AutoDock4OutputError,
    AutoDock4Parameters,
    AutoGrid4Parameters,
    parse_autodock4_dlg,
    plan_autodock4_command,
    plan_autogrid4_command,
    render_autodock4_dpf,
    render_autogrid4_gpf,
)
from caddsuite.contracts.structure import BindingSite, BindingSiteMethod
from caddsuite.domain.identity import new_ulid


def _site() -> BindingSite:
    return BindingSite(
        id=new_ulid(),
        target_id=new_ulid(),
        method=BindingSiteMethod.COORDINATES,
        center_A=(1.0, 2.0, 3.0),
        size_A=(22.0, 21.0, 20.0),
    )


def _parameters() -> AutoDock4Parameters:
    return AutoDock4Parameters(
        seed=(12345, 67890),
        ga_runs=25,
        ga_pop_size=150,
        ga_num_evals=2_500_000,
        ga_num_generations=27_000,
        ga_elitism=1,
        ga_mutation_rate=0.02,
        ga_crossover_rate=0.8,
        ga_window_size=10,
        rmsd_threshold_A=2.0,
    )


def _dlg(*, duplicate_run: bool = False) -> str:
    models = []
    for model, run, energy in ((1, 17, -8.75), (2, 29, -7.25)):
        if duplicate_run and model == 2:
            run = 17
        models.extend(
            (
                f"DOCKED: MODEL {model}",
                f"DOCKED: USER Run = {run}",
                f"DOCKED: USER Estimated Free Energy of Binding = {energy:.2f} kcal/mol [=(1)+(2)]",
                "DOCKED: REMARK INDEX MAP 1 1 2 2",
                "DOCKED: ROOT",
                "DOCKED: ATOM 1 C LIG 1 1.000 2.000 3.000 C",
                "DOCKED: ENDROOT",
                "DOCKED: TORSDOF 0",
                "DOCKED: ENDMDL",
            )
        )
    return "AutoDock 4.2.6\n" + "\n".join(models) + "\n"


def test_autogrid4_gpf_matches_atom_types_and_site_geometry() -> None:
    gpf = render_autogrid4_gpf(
        receptor_pdbqt="receptor.pdbqt",
        map_stem="target",
        receptor_types=("A", "C", "HD", "NA", "OA"),
        ligand_types=("C", "HD", "NA", "OA"),
        site=_site(),
        parameters=AutoGrid4Parameters(npts=(60, 58, 54), spacing_A=0.375),
    )
    assert "gridcenter 1.000000 2.000000 3.000000" in gpf
    assert "receptor_types A C HD NA OA" in gpf
    assert "ligand_types C HD NA OA" in gpf
    assert "map target.NA.map" in gpf
    assert "elecmap target.e.map" in gpf
    assert "dsolvmap target.d.map" in gpf


def test_autogrid4_refuses_mesh_that_does_not_cover_site() -> None:
    with pytest.raises(ValueError, match="does not cover"):
        render_autogrid4_gpf(
            receptor_pdbqt="receptor.pdbqt",
            map_stem="target",
            receptor_types=("C",),
            ligand_types=("C",),
            site=_site(),
            parameters=AutoGrid4Parameters(npts=(40, 40, 40), spacing_A=0.375),
        )
    with pytest.raises(ValidationError, match="even integers"):
        AutoGrid4Parameters(npts=(59, 60, 60), spacing_A=0.375)


def test_dpf_contains_fixed_seeds_and_all_search_settings() -> None:
    dpf = render_autodock4_dpf(
        ligand_pdbqt="ligand.pdbqt",
        map_stem="target",
        ligand_types=("A", "C", "HD", "NA", "OA"),
        torsdof=7,
        about_A=(1.0, 2.0, 3.0),
        parameters=_parameters(),
    )
    assert "seed 12345 67890" in dpf
    assert "ga_run 25" in dpf
    assert "ga_num_evals 2500000" in dpf
    assert "torsdof 7" in dpf
    assert "analysis" in dpf
    assert "seed pid time" not in dpf
    assert "Ki" not in dpf


def test_dpf_refuses_paths_that_escape_isolated_job_directory() -> None:
    with pytest.raises(ValueError, match="basename"):
        render_autodock4_dpf(
            ligand_pdbqt="../ligand.pdbqt",
            map_stem="target",
            ligand_types=("C",),
            torsdof=0,
            about_A=(0.0, 0.0, 0.0),
            parameters=_parameters(),
        )
    with pytest.raises(ValidationError, match="distinct"):
        AutoDock4Parameters.model_validate({**_parameters().model_dump(), "seed": (7, 7)})


def test_dlg_parser_normalizes_scores_and_keeps_each_raw_pose_block() -> None:
    poses = parse_autodock4_dlg(_dlg())
    assert [(pose.model_index, pose.run_index) for pose in poses] == [(1, 17), (2, 29)]
    assert [pose.score_kcal_mol for pose in poses] == [-8.75, -7.25]
    assert "REMARK INDEX MAP" in poses[0].pdbqt_text
    assert "ATOM 1 C" in poses[0].pdbqt_text
    assert "Estimated Inhibition Constant" not in poses[0].pdbqt_text


def test_dlg_parser_rejects_missing_chemistry_and_duplicate_run_ids() -> None:
    with pytest.raises(AutoDock4OutputError, match="no complete scored pose"):
        parse_autodock4_dlg("AutoDock 4.2.6\n")
    malformed = (
        _dlg()
        .replace("DOCKED: ATOM", "DOCKED: USER NOTE")
        .replace("DOCKED: REMARK INDEX MAP", "DOCKED: REMARK INDEX MAP", 1)
    )
    with pytest.raises(AutoDock4OutputError, match="contains no ligand atoms"):
        parse_autodock4_dlg(malformed)
    with pytest.raises(AutoDock4OutputError, match="repeats a run"):
        parse_autodock4_dlg(_dlg(duplicate_run=True))


def test_autogrid_and_autodock_command_plans_are_argv_only(tmp_path: Path) -> None:
    executable = tmp_path / "autodock"
    executable.write_text("binary placeholder")
    gpf = tmp_path / "grid.gpf"
    gpf.write_text("npts 60 60 60\n")
    dpf = tmp_path / "dock.dpf"
    dpf.write_text("analysis\n")
    grid = plan_autogrid4_command(
        executable=executable,
        gpf_file=gpf,
        glg_file=tmp_path / "grid.glg",
        working_directory=tmp_path,
    )
    dock = plan_autodock4_command(
        executable=executable,
        dpf_file=dpf,
        dlg_file=tmp_path / "dock.dlg",
        working_directory=tmp_path,
    )
    assert grid.argv == (str(executable), "-p", "grid.gpf", "-l", "grid.glg")
    assert dock.argv == (str(executable), "-p", "dock.dpf", "-l", "dock.dlg")
    assert grid.cwd == dock.cwd == tmp_path
