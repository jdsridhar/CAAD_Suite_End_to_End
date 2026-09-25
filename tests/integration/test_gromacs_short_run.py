"""Short CPU-only production smoke test using a temporary copy of the audited system."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

from caddsuite.adapters.md.gromacs import (
    GromacsMDAdapter,
    classify_grompp_warnings,
    normalize_index_final_newline,
    parse_gromacs_progress,
)
from caddsuite.adapters.system_builders.charmm_gui_import import (
    CharmmGuiGromacsImportAdapter,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.md import MDProtocol, MDStage, MDStageInput, MDStageKind
from caddsuite.contracts.system import SystemBuildRequest, SystemBuildResult
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import AdapterContext

GROMACS = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
pytestmark = [
    pytest.mark.engine("gromacs"),
    pytest.mark.skipif(
        not GROMACS or not DATA_ROOT,
        reason="set CADDSUITE_GROMACS_EXECUTABLE and CADDSUITE_MDSUITE_DATA to run GROMACS",
    ),
]


def _artifact(role: str, payload: bytes) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=new_ulid(), role=role, sha256=hashlib.sha256(payload).hexdigest()
    )


def _software(name: str, version: str, kind: SoftwareKind) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version=version,
        kind=kind,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )


def _import_real_system(
    source: Path, stage_dir: Path
) -> tuple[SystemBuildResult, dict[str, bytes]]:
    paths = [
        "topol.top",
        "step3_input.gro",
        "index.ndx",
        "analysis/analysis.ndx",
        "step4.0_minimization.mdp",
        "step4.1_equilibration.mdp",
        "step5_production.mdp",
    ]
    paths.extend(
        path.relative_to(source).as_posix()
        for path in sorted((source / "toppar").rglob("*"))
        if path.is_file() and ":Zone.Identifier" not in path.name
    )
    files = {relative: (source / relative).read_bytes() for relative in paths}
    refs = {path: _artifact(f"bundle_file:{path}", payload) for path, payload in files.items()}
    complex_model = Complex(
        id=new_ulid(),
        compound_id=new_ulid(),
        form_id=new_ulid(),
        target_id=new_ulid(),
        structure_id=new_ulid(),
        prepared_receptor_id=new_ulid(),
        docking_run_id=new_ulid(),
        pose_id=new_ulid(),
        protein=ArtifactRef(artifact_id=new_ulid(), role="protein"),
        ligand=ArtifactRef(artifact_id=new_ulid(), role="ligand"),
        assembled=ArtifactRef(artifact_id=new_ulid(), role="complex"),
        protein_atom_count=1,
        ligand_atom_count=48,
        ligand_heavy_atom_count=1,
        coordinate_fidelity_max_dev_A=0.0,
    )
    request = SystemBuildRequest(
        id=new_ulid(),
        complex_id=complex_model.id,
        compound_id=complex_model.compound_id,
        form_id=complex_model.form_id,
        target_id=complex_model.target_id,
        pose_id=complex_model.pose_id,
        source_artifacts=refs,
        selections={"ligand": "LIG", "protein": "Protein"},
        mode="import",
        parameters={
            "ff_family": "charmm",
            "protein_ff": "CHARMM36m",
            "ligand_method": "CGenFF",
            "ligand_charge_model": "CGenFF",
            "water_model": "CHARMM TIP3P",
            "ion_parameters": "CHARMM ions",
            "ligand_resnames": ["LIG"],
            "ligand_molecule_types": ["LIG"],
            "protein_molecule_types": ["PROA"],
            "selection_index_path": "analysis/analysis.ndx",
        },
    )
    for relative, payload in files.items():
        destination = stage_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    context = AdapterContext(
        inputs={"request": request, "complex": complex_model},
        parameters={},
        working_directory=stage_dir,
    )
    result = CharmmGuiGromacsImportAdapter().normalize_result({}, context)
    return result, files


def _short_mdp(original: bytes, *, n_steps: int) -> bytes:
    lines = original.decode("utf-8").splitlines()
    seen: set[str] = set()
    updated: list[str] = []
    replacements = {"dt": "0.002", "nsteps": str(n_steps)}
    for line in lines:
        assignment, separator, comment = line.partition(";")
        if "=" in assignment:
            key, _value = assignment.split("=", 1)
            normalized_key = key.strip().lower()
            if normalized_key in replacements:
                assert normalized_key not in seen
                seen.add(normalized_key)
                suffix = f" ;{comment}" if separator else ""
                line = f"{key.rstrip()} = {replacements[normalized_key]}{suffix}"
        updated.append(line)
    assert seen == set(replacements)
    return ("\n".join(updated) + "\n").encode("utf-8")


def _prepare_real_stage(
    source: Path, stage_dir: Path, *, n_steps: int
) -> tuple[GromacsMDAdapter, AdapterContext, dict[str, bytes], bytes]:
    stage_dir.mkdir()
    build, source_files = _import_real_system(source, stage_dir)
    equilibrated = (source / "step4.1_equilibration.gro").read_bytes()
    original_index = source_files["index.ndx"]
    normalized_index, changed = normalize_index_final_newline(original_index)
    assert changed
    mdp_payload = _short_mdp(source_files["step5_production.mdp"], n_steps=n_steps)
    (stage_dir / "step4.1_equilibration.gro").write_bytes(equilibrated)
    (stage_dir / "smoke.mdp").write_bytes(mdp_payload)
    (stage_dir / "index.normalized.ndx").write_bytes(normalized_index)

    protocol = build.protocol
    assert protocol is not None
    production = protocol.stages[-1]
    smoke_production = MDStage(
        kind=MDStageKind.PRODUCTION,
        integrator=production.integrator,
        timestep_fs=2.0,
        n_steps=n_steps,
        temperature_K=production.temperature_K,
        thermostat=production.thermostat,
        pressure_bar=production.pressure_bar,
        barostat=production.barostat,
        constraints=production.constraints,
        nonbonded=production.nonbonded,
    )
    smoke_protocol = MDProtocol(stages=(*protocol.stages[:-1], smoke_production))
    build = build.model_copy(update={"protocol": smoke_protocol})
    topology_ref = build.system.engine_inputs["gromacs"]["topol.top"]
    stage_input = MDStageInput(
        id=new_ulid(),
        system_id=build.system.id,
        stage_index=2,
        artifacts={
            "topology": topology_ref,
            "md_parameters": _artifact("smoke_mdp", mdp_payload),
            "coordinates": _artifact("equilibrated_coordinates", equilibrated),
            "index": _artifact("normalized_index", normalized_index),
        },
    )
    parameters = {
        "stage_index": 2,
        "executable": GROMACS,
        "mdp_path": "smoke.mdp",
        "coordinates_path": "step4.1_equilibration.gro",
        "topology_path": "topol.top",
        "index_path": "index.normalized.ndx",
        "output_prefix": "smoke",
        "resource_mode": "cpu",
        "cpu_threads": 1,
        "gpu_ids": (),
    }
    context = AdapterContext(
        inputs={"system_build": build, "stage_input": stage_input},
        parameters={"gromacs": parameters},
        working_directory=stage_dir,
    )
    return GromacsMDAdapter(), context, source_files, equilibrated


def _run(argv: tuple[str, ...], cwd: Path, extra_env: dict[str, str]):
    env = os.environ.copy()
    env["PATH"] = f"{Path(argv[0]).parent}{os.pathsep}{env.get('PATH', '')}"
    env.update(extra_env)
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
        shell=False,
        timeout=120,
    )


def test_gromacs_executes_50_step_cpu_production_on_a_temporary_copy(tmp_path: Path):
    assert GROMACS is not None
    assert DATA_ROOT is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    stage_dir = tmp_path / "smoke_stage"
    adapter, context, source_files, equilibrated = _prepare_real_stage(
        source, stage_dir, n_steps=50
    )
    assert adapter.validate_stage(context) == ()
    plan = adapter.plan_stage(context)
    assert len(plan.commands) == 2
    assert "-maxwarn" not in plan.commands[0].argv

    grompp = _run(plan.commands[0].argv, stage_dir, dict(plan.commands[0].environment))
    grompp_issues = classify_grompp_warnings(grompp.stdout, grompp.stderr)
    assert grompp.returncode == 0, (grompp.stdout + grompp.stderr).decode(errors="replace")[-4000:]
    assert grompp_issues == ()
    assert (stage_dir / "smoke.tpr").is_file()

    mdrun = _run(plan.commands[1].argv, stage_dir, dict(plan.commands[1].environment))
    assert mdrun.returncode == 0, (mdrun.stdout + mdrun.stderr).decode(errors="replace")[-4000:]
    for suffix in ("gro", "log", "edr", "cpt"):
        artifact = stage_dir / f"smoke.{suffix}"
        assert artifact.is_file()
        assert artifact.stat().st_size > 0
    assert re.search(rb"\bStep\s+50\b", (stage_dir / "smoke.log").read_bytes(), re.IGNORECASE)
    for relative, payload in source_files.items():
        assert (
            hashlib.sha256((source / relative).read_bytes()).hexdigest()
            == hashlib.sha256(payload).hexdigest()
        )
    assert (source / "step4.1_equilibration.gro").read_bytes() == equilibrated

    progress = parse_gromacs_progress(mdrun.stdout, total_steps=50, aggregate_log=mdrun.stderr)
    assert progress is None or progress.completed_steps <= 50


def test_gromacs_interrupts_and_resumes_from_checkpoint_on_a_temporary_copy(tmp_path: Path):
    assert GROMACS is not None
    assert DATA_ROOT is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    stage_dir = tmp_path / "resume_stage"
    adapter, context, source_files, equilibrated = _prepare_real_stage(
        source, stage_dir, n_steps=2_000
    )
    gromacs_parameters = context.parameters["gromacs"]
    assert isinstance(gromacs_parameters, dict)
    gromacs_parameters.update(
        {"checkpoint_interval_minutes": 0.001, "maximum_runtime_hours": 0.00005}
    )
    assert adapter.validate_stage(context) == ()
    plan = adapter.plan_stage(context)
    assert len(plan.commands) == 2
    assert "-maxh" in plan.commands[1].argv
    assert "-cpt" in plan.commands[1].argv

    grompp = _run(plan.commands[0].argv, stage_dir, dict(plan.commands[0].environment))
    grompp_issues = classify_grompp_warnings(grompp.stdout, grompp.stderr)
    assert grompp.returncode == 0, (grompp.stdout + grompp.stderr).decode(errors="replace")[-4000:]
    assert grompp_issues == ()
    tpr = stage_dir / "smoke.tpr"
    assert tpr.is_file()

    interrupted = _run(plan.commands[1].argv, stage_dir, dict(plan.commands[1].environment))
    interrupted_output = (interrupted.stdout + interrupted.stderr).decode(errors="replace")
    assert interrupted.returncode == 0, interrupted_output[-4000:]
    checkpoint = stage_dir / "smoke.cpt"
    assert checkpoint.is_file(), interrupted_output[-4000:]
    assert checkpoint.stat().st_size > 0

    dump = _run((GROMACS, "dump", "-cp", "smoke.cpt"), stage_dir, {})
    assert dump.returncode == 0, (dump.stdout + dump.stderr).decode(errors="replace")[-4000:]
    step_match = re.search(rb"\bstep\s*=\s*(\d+)", dump.stdout + dump.stderr)
    assert step_match is not None
    interrupted_step = int(step_match.group(1))
    assert 0 < interrupted_step < 2_000

    build = context.inputs["system_build"]
    assert isinstance(build, SystemBuildResult)
    topology_ref = build.system.engine_inputs["gromacs"]["topol.top"]
    resume_input = MDStageInput(
        id=new_ulid(),
        system_id=build.system.id,
        stage_index=2,
        artifacts={
            "topology": topology_ref,
            "tpr": _artifact("gromacs_tpr", tpr.read_bytes()),
            "resume_checkpoint": _artifact("gromacs_checkpoint", checkpoint.read_bytes()),
        },
    )
    resume_context = AdapterContext(
        inputs={"system_build": build, "stage_input": resume_input},
        parameters={
            "gromacs": {
                "stage_index": 2,
                "executable": GROMACS,
                "topology_path": "topol.top",
                "output_prefix": "smoke",
                "resume_checkpoint_path": "smoke.cpt",
                "resource_mode": "cpu",
                "cpu_threads": 1,
                "gpu_ids": (),
                "checkpoint_interval_minutes": 0.001,
            }
        },
        working_directory=stage_dir,
    )
    assert adapter.validate_stage(resume_context) == ()
    resume_plan = adapter.plan_stage(resume_context)
    assert len(resume_plan.commands) == 1
    assert resume_plan.commands[0].argv[1:] == (
        "mdrun",
        "-v",
        "-deffnm",
        "smoke",
        "-cpi",
        "smoke.cpt",
        "-append",
        "-cpt",
        "0.001",
        "-ntomp",
        "1",
        "-pin",
        "on",
        "-pinoffset",
        "0",
    )

    resumed = _run(
        resume_plan.commands[0].argv,
        stage_dir,
        dict(resume_plan.commands[0].environment),
    )
    assert resumed.returncode == 0, (resumed.stdout + resumed.stderr).decode(errors="replace")[
        -4000:
    ]
    assert re.search(rb"\bStep\s+2000\b", (stage_dir / "smoke.log").read_bytes(), re.IGNORECASE)
    assert (stage_dir / "smoke.gro").is_file()
    assert (stage_dir / "smoke.cpt").is_file()

    for relative, payload in source_files.items():
        assert (source / relative).read_bytes() == payload
    assert (source / "step4.1_equilibration.gro").read_bytes() == equilibrated
