"""Opt-in 11-frame G-MD-2 regression on copied 2M2D_LIG inputs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from caddsuite.adapters.binding_energy.gmx_mmpbsa import (
    GromacsMMPBSAAdapter,
    GromacsMMPBSAParameters,
)
from caddsuite.adapters.binding_energy.gmx_mmpbsa_results import parse_gmx_mmpbsa_results
from caddsuite.contracts.analysis import BindingEnergyMethod, BindingEnergyRequest, FrameSelection
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import (
    AtomSelection,
    BoxSpec,
    ComponentForceField,
    ForceFieldComponent,
    ForceFieldFamily,
    MDProtocol,
    MDSimulation,
    MDStage,
    MDStageKind,
    MDSystem,
    Parameterization,
    Trajectory,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid

DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
GMX = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
MMPBSA = os.environ.get("CADDSUITE_GMX_MMPBSA_EXECUTABLE")
MMPBSA_PYTHON = os.environ.get("CADDSUITE_GMX_MMPBSA_PYTHON")
RUN_SHORT = os.environ.get("CADDSUITE_RUN_GMD_MMPBSA_SHORT") == "1"
pytestmark = [
    pytest.mark.engine("gmx_MMPBSA"),
    pytest.mark.legacy_data,
    pytest.mark.slow,
    pytest.mark.skipif(
        not RUN_SHORT or not DATA_ROOT or not GMX or not MMPBSA or not MMPBSA_PYTHON,
        reason=("set CADDSUITE_RUN_GMD_MMPBSA_SHORT=1, MD data, GROMACS, and gmx_MMPBSA paths"),
    ),
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _software(name: str, version: str, kind: SoftwareKind) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version=version,
        kind=kind,
        license_class=LicenseClass.UNKNOWN,
    )


def _group_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    group: str | None = None
    atoms: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            if group is not None:
                counts[group] = len(atoms)
            group = stripped[1:-1].strip()
            atoms = []
        elif group in {"Protein", "LIG"}:
            atoms.extend(int(value) for value in stripped.split())
    if group is not None:
        counts[group] = len(atoms)
    return counts


def _mdp(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        active = line.split(";", 1)[0].strip()
        if "=" in active:
            key, value = active.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _stage_request(source: Path, stage: Path) -> tuple[BindingEnergyRequest, dict[str, Path]]:
    relative_files = [
        "topol.top",
        "step5_1.tpr",
        "step5_1.gro",
        "step5_production.mdp",
        "analysis/analysis.ndx",
        "analysis/combined_fit.xtc",
        "toppar/forcefield.itp",
        "toppar/PROA.itp",
        "toppar/LIG.itp",
        "toppar/POT.itp",
        "toppar/CLA.itp",
        "toppar/TIP3.itp",
    ]
    refs: dict[str, ArtifactRef] = {}
    staged: dict[str, Path] = {}
    for relative in relative_files:
        original = source / relative
        output = stage / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, output)
        ref = ArtifactRef(
            artifact_id=new_ulid(),
            role=relative,
            sha256=_sha256(output),
        )
        refs[relative] = ref
        staged[str(ref.artifact_id)] = output

    ndx = stage / "analysis/analysis.ndx"
    counts = _group_counts(ndx)
    atom_count = int((stage / "step5_1.gro").read_text(encoding="utf-8").splitlines()[1].strip())
    box = tuple(
        float(value)
        for value in (stage / "step5_1.gro").read_text(encoding="utf-8").splitlines()[-1].split()
    )
    mdp = _mdp(stage / "step5_production.mdp")
    dt_fs = float(mdp["dt"]) * 1000.0
    n_steps = int(mdp["nsteps"])
    temperatures = [float(value) for value in mdp["ref_t"].split()]
    pressures = [float(value) for value in mdp["ref_p"].split()]

    parameterization_id = new_ulid()
    parameterization = Parameterization(
        id=parameterization_id,
        ff_family=ForceFieldFamily.CHARMM,
        protein_ff="CHARMM36m",
        ligand_method="CGenFF",
        ligand_charge_model="CGenFF",
        water_model="CHARMM TIP3P",
        ion_parameters="CHARMM ions",
        tool=_software("CHARMM-GUI", "unknown", SoftwareKind.SERVICE),
        compatibility_profile_id="caddsuite.charmm_gui.gromacs.charmm36m_cgenff_v1",
        component_force_fields={
            ForceFieldComponent.PROTEIN: ComponentForceField(
                family=ForceFieldFamily.CHARMM, name="CHARMM36m"
            ),
            ForceFieldComponent.LIGAND: ComponentForceField(
                family=ForceFieldFamily.CHARMM, name="CGenFF"
            ),
            ForceFieldComponent.WATER: ComponentForceField(
                family=ForceFieldFamily.CHARMM, name="CHARMM TIP3P"
            ),
            ForceFieldComponent.IONS: ComponentForceField(
                family=ForceFieldFamily.CHARMM, name="CHARMM ions"
            ),
        },
        quality={"topology_format": "GROMACS"},
        artifacts={name: refs[name] for name in relative_files if name.startswith("toppar/")},
    )
    system_id = new_ulid()
    index = refs["analysis/analysis.ndx"]
    system = MDSystem(
        id=system_id,
        parameterization_id=parameterization_id,
        builder=_software("CHARMM-GUI", "unknown", SoftwareKind.SERVICE),
        box=BoxSpec(
            shape="rectangular",
            vectors_nm=(
                (box[0], 0.0, 0.0),
                (0.0, box[1], 0.0),
                (0.0, 0.0, box[2]),
            ),
        ),
        n_atoms=atom_count,
        net_charge=0.0,
        selections={
            "protein": AtomSelection(
                description="Protein",
                n_atoms=counts["Protein"],
                indices=index,
                verified=True,
            ),
            "ligand": AtomSelection(
                description="LIG",
                n_atoms=counts["LIG"],
                indices=index,
                verified=True,
            ),
        },
        engine_inputs={
            "gromacs": {
                "topol.top": refs["topol.top"],
                "analysis/analysis.ndx": index,
            }
        },
    )
    simulation_id = new_ulid()
    simulation = MDSimulation(
        id=simulation_id,
        accession="CMP0001_MD_001",
        system_id=system_id,
        protocol=MDProtocol(
            stages=(
                MDStage(
                    kind=MDStageKind.PRODUCTION,
                    integrator="md",
                    timestep_fs=dt_fs,
                    n_steps=n_steps,
                    temperature_K=temperatures[0],
                    thermostat=mdp["tcoupl"],
                    pressure_bar=pressures[0],
                    barostat=mdp["pcoupl"],
                ),
            )
        ),
        engine=_software("GROMACS", "2026.3-conda_forge", SoftwareKind.ENGINE),
        adapter=_software("caddsuite.gromacs", "0.1.0", SoftwareKind.ADAPTER),
        total_ns=100.0,
    )
    trajectory = Trajectory(
        id=new_ulid(),
        simulation_id=simulation_id,
        files=(refs["analysis/combined_fit.xtc"],),
        topology=refs["step5_1.tpr"],
        n_frames=1001,
        frame_interval_ps=100.0,
        time_range_ns=(0.0, 100.0),
        processing=("legacy combined_fit",),
    )
    request = BindingEnergyRequest(
        id=new_ulid(),
        accession="CMP0001_MMPBSA_001",
        system=system,
        parameterization=parameterization,
        simulation=simulation,
        trajectory=trajectory,
        trajectory_artifact=refs["analysis/combined_fit.xtc"],
        method=BindingEnergyMethod.MM_GBSA,
        frames=FrameSelection(
            start_frame=1,
            end_frame=11,
            stride=1,
            n_used=11,
            window_ns=(0.0, 1.0),
        ),
        salt_concentration_M=0.150,
        model={
            "igb": 5,
            "pbradii": "mbondi2",
            "internal_dielectric": 1.0,
            "external_dielectric": 78.5,
            "surface_tension": 0.0072,
            "surface_offset": 0.0,
            "molecular_surface": False,
        },
        source_artifacts=refs,
        selection_groups={"protein": "Protein", "ligand": "LIG"},
        topology_format="GROMACS TPR",
        trajectory_format="XTC",
    )
    return request, staged


def _artifact(path: Path) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=path.name, sha256=_sha256(path))


def test_11_frame_result_matches_archived_per_frame_components(tmp_path: Path):
    assert DATA_ROOT is not None
    assert GMX is not None
    assert MMPBSA is not None
    assert MMPBSA_PYTHON is not None
    source = Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    analysis = source / "analysis"
    old_csv = analysis / "FINAL_RESULTS_MMGBSA.csv"
    old_dat = analysis / "FINAL_RESULTS_MMGBSA.dat"
    protected_sources = [
        source / "topol.top",
        source / "step5_1.tpr",
        source / "step5_1.gro",
        analysis / "analysis.ndx",
        analysis / "combined_fit.xtc",
        old_csv,
        old_dat,
    ]
    before = {path: _sha256(path) for path in protected_sources}
    stage = tmp_path / "stage"
    stage.mkdir()
    request, staged = _stage_request(source, stage)
    adapter = GromacsMMPBSAAdapter()
    assert adapter.validate_request(request) == ()
    parameters = GromacsMMPBSAParameters(
        gmx_mmpbsa_executable=MMPBSA,
        gmx_executable=GMX,
        ambertools_bin=str(Path(MMPBSA).resolve().parent),
        python_executable=MMPBSA_PYTHON,
        worker_script=str(
            Path(__file__).resolve().parents[2] / "src/caddsuite_worker/gmx_mmpbsa_worker.py"
        ),
        timeout_seconds=3600,
        mpi_launch_retries=0,
    )
    plan = adapter.plan_request(
        request,
        parameters=parameters.model_dump(),
        staged_inputs=staged,
        working_directory=stage,
    )
    worker_request = adapter.worker_request(
        request,
        parameters=parameters,
        staged_inputs=staged,
        working_directory=stage,
    )
    request_path = stage / parameters.request_path
    request_path.write_text(json.dumps(worker_request, indent=2), encoding="utf-8")
    command = plan.commands[0]
    completed = subprocess.run(
        command.argv,
        cwd=command.working_directory,
        capture_output=True,
        check=False,
        shell=False,
        timeout=3700,
    )
    assert completed.returncode == 0, (
        completed.stdout.decode("utf-8", errors="replace")
        + "\n"
        + completed.stderr.decode("utf-8", errors="replace")
    )

    output = stage / parameters.output_dir
    worker_result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    dat_path = stage / worker_result["report_dat"]
    csv_path = stage / worker_result["report_csv"]
    worker_result["dat_text"] = dat_path.read_text(encoding="utf-8")
    worker_result["csv_text"] = csv_path.read_text(encoding="utf-8")
    output_artifacts = {
        path.name: _artifact(path)
        for path in (
            dat_path,
            csv_path,
            output / "mmpbsa.in",
            output / "commands.json",
            output / "result.json",
        )
    }
    log_artifacts = {
        path.name: _artifact(path)
        for path in (
            output / "gromacs_version.stdout.txt",
            output / "gromacs_version.stderr.txt",
            output / "gmx_mmpbsa.attempt-1.stdout.txt",
            output / "gmx_mmpbsa.attempt-1.stderr.txt",
        )
    }
    normalized = adapter.normalize_result(
        request,
        worker_result,
        source_artifacts=request.source_artifacts,
        output_artifacts=output_artifacts,
        log_artifacts=log_artifacts,
    )
    archived = parse_gmx_mmpbsa_results(
        old_dat.read_text(encoding="utf-8"), old_csv.read_text(encoding="utf-8")
    )
    reproduced = parse_gmx_mmpbsa_results(worker_result["dat_text"], worker_result["csv_text"])
    assert reproduced.frame_count == 11
    assert reproduced.temperature_K == pytest.approx(303.15)
    assert worker_result["effective_parameters"]["gromacs_group_indices_zero_based"] == [1, 13]
    assert normalized.statistics.mean == pytest.approx(
        sum(reproduced.frame_tables["delta"].values_for("TOTAL")) / 11,
        abs=0.011,
    )
    assert reproduced.frame_tables["delta"].columns == archived.frame_tables["delta"].columns
    component_errors: dict[str, float] = {}
    for column in archived.frame_tables["delta"].columns[1:]:
        observed = reproduced.frame_tables["delta"].values_for(column)
        reference = archived.frame_tables["delta"].values_for(column)[:11]
        component_errors[column] = max(abs(a - b) for a, b in zip(observed, reference, strict=True))
        assert component_errors[column] <= 0.011, column
    assert {path: _sha256(path) for path in protected_sources} == before
    print(
        "G-MD-18: 11-frame MM/GBSA ",
        f"delta-total={normalized.statistics.mean:.2f} kcal/mol; ",
        f"max per-frame component difference={max(component_errors.values()):.4f} kcal/mol; ",
        f"max by component={component_errors}",
        sep="",
    )
