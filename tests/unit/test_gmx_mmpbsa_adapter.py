"""Planner, named-group, topology-closure, and normalizer tests for gmx_MMPBSA."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from caddsuite.adapters.binding_energy.gmx_mmpbsa import (
    GromacsMMPBSAAdapter,
    GromacsMMPBSAParameters,
    GromacsMMPBSAPlanError,
    validate_topology_include_closure,
)
from caddsuite.contracts.analysis import BindingEnergyRequest, FrameSelection
from caddsuite.contracts.base import ArtifactRef
from caddsuite.domain.identity import new_ulid
from caddsuite_worker.gmx_mmpbsa_worker import (
    WorkerFailure,
    _model_text,
    _read_index,
)
from caddsuite_worker.gmx_mmpbsa_worker import (
    _run as run_worker,
)
from tests.unit.test_binding_energy_request import _request_data
from tests.unit.test_gmx_mmpbsa_results import _report_pair


def _stage(tmp_path: Path) -> tuple[BindingEnergyRequest, dict[str, Path]]:
    data = _request_data()
    payloads = {
        "trajectory.xtc": b"XTC test bytes\n",
        "run.tpr": b"TPR test bytes\n",
        "index.ndx": (
            b"[ System ]\n1 2 3 4 5 6 7 8 9 10\n[ Protein ]\n1 2 3 4 5 6 7 8\n[LIG]\n9 10\n"
        ),
        "topol.top": b'#include "toppar/forcefield.itp"\n[ system ]\nfixture\n',
        "toppar/forcefield.itp": b"; test force-field include\n",
    }

    refs = {
        path: ArtifactRef.model_validate(
            {
                **data["source_artifacts"][path].model_dump(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        for path, payload in payloads.items()
    }
    old_trajectory = data["trajectory"]
    trajectory = old_trajectory.model_copy(
        update={
            "files": (refs["trajectory.xtc"],),
            "topology": refs["run.tpr"],
        }
    )
    old_system = data["system"]
    old_selections = old_system.selections
    system = old_system.model_copy(
        update={
            "selections": {
                "protein": old_selections["protein"].model_copy(
                    update={"indices": refs["index.ndx"]}
                ),
                "ligand": old_selections["ligand"].model_copy(
                    update={"indices": refs["index.ndx"]}
                ),
            },
            "engine_inputs": {
                "gromacs": {
                    "index.ndx": refs["index.ndx"],
                    "topol.top": refs["topol.top"],
                }
            },
        }
    )
    old_parameterization = data["parameterization"]
    parameterization = old_parameterization.model_copy(
        update={"artifacts": {"toppar/forcefield.itp": refs["toppar/forcefield.itp"]}}
    )
    data.update(
        {
            "trajectory": trajectory,
            "trajectory_artifact": refs["trajectory.xtc"],
            "system": system,
            "parameterization": parameterization,
            "source_artifacts": refs,
        }
    )
    root = tmp_path
    staged: dict[str, Path] = {}
    for path, payload in payloads.items():
        staged_path = root / path
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(payload)
        staged[str(refs[path].artifact_id)] = staged_path
    return BindingEnergyRequest.model_validate(data), staged


def _runtime_parameters(tmp_path: Path) -> dict[str, object]:
    amber_bin = tmp_path / "ambertools"
    amber_bin.mkdir(exist_ok=True)
    for name in ("cpptraj", "tleap", "parmchk2", "sander"):
        dependency = amber_bin / name
        if not dependency.exists():
            dependency.symlink_to("/bin/true")
    return GromacsMMPBSAParameters(
        gmx_mmpbsa_executable="/bin/true",
        gmx_executable="/bin/true",
        ambertools_bin=str(amber_bin),
        python_executable="/usr/bin/python3",
        worker_script=str(Path(__file__).parents[2] / "src/caddsuite_worker/gmx_mmpbsa_worker.py"),
    ).model_dump()


def test_adapter_validates_reviewed_profile_and_plans_by_named_group(tmp_path: Path):
    request, staged = _stage(tmp_path)
    adapter = GromacsMMPBSAAdapter()

    assert adapter.validate_request(request) == ()
    payload = adapter.worker_request(
        request,
        parameters=GromacsMMPBSAParameters.model_validate(_runtime_parameters(tmp_path)),
        staged_inputs=staged,
        working_directory=tmp_path,
    )
    assert payload["topology_include_closure"] == ["topol.top", "toppar/forcefield.itp"]
    assert payload["paths"]["index"] == "index.ndx"
    assert payload["selections"] == {
        "protein": {"group_name": "Protein", "n_atoms": 8},
        "ligand": {"group_name": "LIG", "n_atoms": 2},
    }
    assert payload["selection_group_indices_zero_based"] == {"protein": 1, "ligand": 2}

    plan = adapter.plan_request(
        request,
        parameters=_runtime_parameters(tmp_path),
        staged_inputs=staged,
        working_directory=tmp_path,
    )
    assert len(plan.commands) == 1
    assert plan.commands[0].argv[0] == "/usr/bin/python3"
    assert "-O" not in plan.commands[0].argv
    assert "FINAL_RESULTS_MMGBSA.csv" in plan.expected_outputs[4]


def test_adapter_blocks_unknown_force_field_profile_and_entropy(tmp_path: Path):
    request, _ = _stage(tmp_path)
    changed_parameterization = request.parameterization.model_copy(
        update={"compatibility_profile_id": "unreviewed.profile"}
    )
    changed = request.model_copy(update={"parameterization": changed_parameterization})
    assert any(
        "reviewed CHARMM-GUI" in issue.message
        for issue in GromacsMMPBSAAdapter().validate_request(changed)
    )


def test_input_stage_must_preserve_hash_checked_topology_tree(tmp_path: Path):
    request, staged = _stage(tmp_path)
    forcefield = request.parameterization.artifacts["toppar/forcefield.itp"]
    (tmp_path / "toppar/forcefield.itp").write_bytes(b"modified\n")
    with pytest.raises(GromacsMMPBSAPlanError, match="SHA-256"):
        GromacsMMPBSAAdapter().worker_request(
            request,
            parameters=GromacsMMPBSAParameters.model_validate(_runtime_parameters(tmp_path)),
            staged_inputs=staged,
            working_directory=tmp_path,
        )
    assert forcefield.sha256 is not None


def test_topology_include_closure_rejects_missing_or_escaping_include(tmp_path: Path):
    root = tmp_path / "topol.top"
    root.write_text('#include "../outside.itp"\n', encoding="utf-8")
    with pytest.raises(GromacsMMPBSAPlanError, match="canonical and relative"):
        validate_topology_include_closure("topol.top", {"topol.top": root})

    root.write_text('#include "missing.itp"\n', encoding="utf-8")
    with pytest.raises(GromacsMMPBSAPlanError, match="unstaged file"):
        validate_topology_include_closure("topol.top", {"topol.top": root})


def test_named_index_group_parser_checks_range_duplicates_and_empty_groups(tmp_path: Path):
    path = tmp_path / "index.ndx"
    path.write_text("[ Protein ]\n1 2\n[LIG]\n3\n", encoding="utf-8")
    groups = _read_index(path, 3)
    assert groups == {"Protein": {1, 2}, "LIG": {3}}

    path.write_text("[ Protein ]\n1 1\n", encoding="utf-8")
    with pytest.raises(WorkerFailure, match="repeats atoms"):
        _read_index(path, 3)

    path.write_text("[ Protein ]\n4\n", encoding="utf-8")
    with pytest.raises(WorkerFailure, match="outside the declared MDSystem"):
        _read_index(path, 3)


def test_worker_input_explicitly_renders_physical_settings_and_protocol_temperature(tmp_path: Path):
    request, staged = _stage(tmp_path)
    payload = GromacsMMPBSAAdapter().worker_request(
        request,
        parameters=GromacsMMPBSAParameters.model_validate(_runtime_parameters(tmp_path)),
        staged_inputs=staged,
        working_directory=tmp_path,
    )
    text = _model_text(payload)
    assert "temperature = 303.15" in text
    assert "PBRadii = 3" in text
    assert "igb = 5" in text
    assert "saltcon = 0.15" in text
    assert "startframe = 1" in text


def test_normalizer_preserves_native_statistics_and_limitation_warning(tmp_path: Path):
    request, _ = _stage(tmp_path)
    request = request.model_copy(
        update={
            "frames": FrameSelection(
                start_frame=1,
                end_frame=2,
                n_used=2,
                window_ns=(0.0, 0.1),
            )
        }
    )
    dat, csv = _report_pair()
    dat = dat.replace("310.00 K", "303.15 K")
    output_ref = ArtifactRef(artifact_id=new_ulid(), role="raw report", sha256="a" * 64)
    log_ref = ArtifactRef(artifact_id=new_ulid(), role="worker log", sha256="b" * 64)
    result = GromacsMMPBSAAdapter().normalize_result(
        request,
        {"dat_text": dat, "csv_text": csv, "effective_parameters": {"test": True}},
        source_artifacts=request.source_artifacts,
        output_artifacts={"summary": output_ref},
        log_artifacts={"stdout": log_ref},
    )
    assert result.components_kcal_per_mol["total"] == pytest.approx(5.25)
    assert result.statistics.sem_naive == pytest.approx(0.18)
    assert result.statistics.sem_block is None
    assert result.native_components_kcal_per_mol["ΔTOTAL"] == pytest.approx(5.25)
    assert result.tool.version == "1.6.3"
    assert any("No entropy" in warning for warning in result.warnings)


def test_normalizer_rejects_report_temperature_conflict(tmp_path: Path):
    request, _ = _stage(tmp_path)
    request = request.model_copy(
        update={
            "frames": FrameSelection(
                start_frame=1,
                end_frame=2,
                n_used=2,
                window_ns=(0.0, 0.1),
            )
        }
    )
    dat, csv = _report_pair()
    with pytest.raises(GromacsMMPBSAPlanError, match="temperature"):
        GromacsMMPBSAAdapter().normalize_result(
            request,
            {"dat_text": dat, "csv_text": csv},
            source_artifacts=request.source_artifacts,
            output_artifacts={
                "summary": ArtifactRef(artifact_id=new_ulid(), role="raw", sha256="a" * 64)
            },
            log_artifacts={},
        )


def test_runtime_parameters_reject_ambiguous_mpi_configuration(tmp_path: Path):
    with pytest.raises(ValidationError, match="mpi_processes > 1"):
        GromacsMMPBSAParameters.model_validate(
            {**_runtime_parameters(tmp_path), "mpi_processes": 4}
        )


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{content}", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_worker_executes_and_retries_only_empty_mpi_launch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, staged = _stage(tmp_path)
    request = request.model_copy(
        update={
            "frames": FrameSelection(
                start_frame=1,
                end_frame=2,
                n_used=2,
                window_ns=(0.0, 0.1),
            )
        }
    )
    dat, csv = _report_pair()
    dat = dat.replace("310.00 K", "303.15 K")
    (tmp_path / "fixture.dat").write_text(dat, encoding="utf-8")
    (tmp_path / "fixture.csv").write_text(csv, encoding="utf-8")
    gmx = _write_executable(
        tmp_path / "fake-gmx",
        'print("GROMACS version: 2026.3-conda_forge")\n',
    )
    mmpbsa = _write_executable(
        tmp_path / "fake-gmx-mmpbsa",
        """
import sys
from pathlib import Path
args = sys.argv[1:]
if args[args.index("-cg") + 1:args.index("-cg") + 3] != ["1", "2"]:
    raise SystemExit(17)
root = Path.cwd()
(root / args[args.index("-o") + 1]).write_bytes((root / "fixture.dat").read_bytes())
(root / args[args.index("-eo") + 1]).write_bytes((root / "fixture.csv").read_bytes())
""",
    )
    launcher = _write_executable(
        tmp_path / "fake-mpirun",
        """
import os
import subprocess
import sys
from pathlib import Path
record = Path(os.environ["CADDSUITE_TEST_MPI_RECORD"])
with record.open("a", encoding="utf-8") as stream:
    stream.write(os.environ["TMPDIR"] + chr(10))
count_file = record.with_suffix(".count")
count = int(count_file.read_text() if count_file.exists() else "0")
count_file.write_text(str(count + 1))
if count == 0:
    raise SystemExit(255)
child = subprocess.run(sys.argv[3:], capture_output=True, check=False)
sys.stdout.buffer.write(child.stdout)
sys.stderr.buffer.write(child.stderr)
raise SystemExit(child.returncode)
""",
    )
    parameters = {
        **_runtime_parameters(tmp_path),
        "gmx_executable": str(gmx),
        "gmx_mmpbsa_executable": str(mmpbsa),
        "ambertools_bin": str(tmp_path / "ambertools"),
        "mpi_launcher": str(launcher),
        "mpi_processes": 2,
    }
    payload = GromacsMMPBSAAdapter().worker_request(
        request,
        parameters=GromacsMMPBSAParameters.model_validate(parameters),
        staged_inputs=staged,
        working_directory=tmp_path,
    )
    request_file = tmp_path / "gmx-mmpbsa.request.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    record = tmp_path / "mpi-tempdirs.txt"
    monkeypatch.setenv("CADDSUITE_TEST_MPI_RECORD", str(record))

    run_worker(request_file, str(payload["paths"]["output_dir"]))

    output = tmp_path / str(payload["paths"]["output_dir"])
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    commands = json.loads((output / "commands.json").read_text(encoding="utf-8"))
    attempts = [
        command
        for command in commands
        if str(command.get("label", "")).startswith("gmx_mmpbsa_attempt_")
    ]
    temporary_directories = record.read_text(encoding="utf-8").splitlines()
    assert len(attempts) == 2
    assert result["effective_parameters"]["attempt_count"] == 2
    assert len(set(temporary_directories)) == 2
    assert all(not Path(directory).exists() for directory in temporary_directories)
    assert (output / "FINAL_RESULTS_MMGBSA.dat").read_text(encoding="utf-8") == dat
    assert (output / "FINAL_RESULTS_MMGBSA.csv").read_text(encoding="utf-8") == csv
    assert (output / "mmpbsa.in").is_file()
    assert (output / "gromacs_version.stdout.txt").is_file()
    assert result["effective_parameters"]["gromacs_group_indices_zero_based"] == [1, 2]


def test_normalizer_populates_selected_block_uncertainty_separately_from_native_sem(tmp_path: Path):
    request, _ = _stage(tmp_path)
    request = request.model_copy(
        update={
            "frames": FrameSelection(
                start_frame=1,
                end_frame=2,
                n_used=2,
                window_ns=(0.0, 0.1),
            )
        }
    )
    data = request.model_dump(mode="python")
    data["uncertainty"] = {"block_size_frames": 1, "minimum_blocks": 2}
    request = BindingEnergyRequest.model_validate(data)
    dat, csv = _report_pair()
    dat = dat.replace("310.00 K", "303.15 K")
    result = GromacsMMPBSAAdapter().normalize_result(
        request,
        {"dat_text": dat, "csv_text": csv},
        source_artifacts=request.source_artifacts,
        output_artifacts={
            "summary": ArtifactRef(artifact_id=new_ulid(), role="raw report", sha256="a" * 64)
        },
        log_artifacts={
            "stdout": ArtifactRef(artifact_id=new_ulid(), role="worker log", sha256="b" * 64)
        },
    )

    assert result.statistics.block_size_frames == 1
    assert result.statistics.sem_block is not None
    assert result.statistics.n_effective == pytest.approx(2.0)
    assert result.block_diagnostics[0].frames_used == 2
    assert result.block_diagnostics[0].n_blocks == 2
    assert any("explicitly selected block size" in warning for warning in result.warnings)
