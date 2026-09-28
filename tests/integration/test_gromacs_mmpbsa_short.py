"""Opt-in 11-frame G-MD-2 regression on copied 2M2D_LIG inputs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caddsuite.adapters.binding_energy.gmx_mmpbsa import (
    GromacsMMPBSAAdapter,
    GromacsMMPBSAParameters,
)
from caddsuite.adapters.binding_energy.gmx_mmpbsa_results import parse_gmx_mmpbsa_results
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.contracts.analysis import (
    BindingEnergyMethod,
    BindingEnergyPlan,
    BindingEnergyRequest,
    FrameSelection,
    TrajectoryAnalysisPlan,
    TrajectoryMetric,
    TrajectoryProcessingRequest,
    TrajectorySegmentInput,
    TrajectoryTransform,
)
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
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.workflow.definition import WorkflowDefinition

DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
STAGE_DATA_ROOT = os.environ.get("CADDSUITE_GMX_MMPBSA_STAGE_DATA")
GMX = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
MMPBSA = os.environ.get("CADDSUITE_GMX_MMPBSA_EXECUTABLE")
MMPBSA_PYTHON = os.environ.get("CADDSUITE_GMX_MMPBSA_PYTHON")
MDA_PYTHON = os.environ.get("CADDSUITE_MDA_PYTHON")
PYSCF_PYTHON = os.environ.get("CADDSUITE_PYSCF_PYTHON")
RUN_SHORT = os.environ.get("CADDSUITE_RUN_GMD_MMPBSA_SHORT") == "1"
pytestmark = [
    pytest.mark.engine("gmx_MMPBSA"),
    pytest.mark.legacy_data,
    pytest.mark.slow,
    pytest.mark.skipif(
        not RUN_SHORT
        or not DATA_ROOT
        or not GMX
        or not MMPBSA
        or not MMPBSA_PYTHON
        or not MDA_PYTHON,
        reason=(
            "set CADDSUITE_RUN_GMD_MMPBSA_SHORT=1, MD data, GROMACS, "
            "gmx_MMPBSA and MDAnalysis paths"
        ),
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


def _stage_request(
    source: Path, stage: Path, *, compound_id: str | None = None, form_id: str | None = None
) -> tuple[BindingEnergyRequest, dict[str, Path]]:
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
    simulation_id = new_ulid()
    compound_id = compound_id or new_ulid()
    form_id = form_id or new_ulid()
    index = refs["analysis/analysis.ndx"]
    system = MDSystem(
        id=system_id,
        compound_id=compound_id,
        form_id=form_id,
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
    simulation = MDSimulation(
        id=simulation_id,
        accession="CMP0001_MD_001",
        system_id=system_id,
        compound_id=compound_id,
        form_id=form_id,
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


def _assert_ligand_topology_matches_form(
    topology_path: Path, structure_path: Path, smiles: str
) -> tuple[str, int]:
    """Guard the external MD-system identity against an explicit standardized molecular form."""
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    lines = topology_path.read_text(encoding="utf-8").splitlines()
    section = ""
    atom_names: list[str] = []
    elements: list[str] = []
    bonds: list[tuple[int, int]] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            continue
        if not stripped or stripped.startswith(";"):
            continue
        fields = stripped.split()
        if section == "atoms" and fields[0].isdigit():
            atom_names.append(fields[4])
            name = fields[4]
            elements.append("H" if name.startswith("H") else "O" if name.startswith("O") else "C")
        elif section == "bonds" and fields[0].isdigit():
            bonds.append((int(fields[0]) - 1, int(fields[1]) - 1))

    molecule = Chem.MolFromSmiles(smiles)
    assert molecule is not None
    reference = Chem.AddHs(molecule)
    Chem.AssignStereochemistry(reference, cleanIt=True, force=True)
    topology_graph = Chem.RWMol()
    for element in elements:
        topology_graph.AddAtom(Chem.Atom(element))
    for first, second in bonds:
        topology_graph.AddBond(first, second, Chem.BondType.SINGLE)
    topology_graph = topology_graph.GetMol()

    # Ignore bond order for the graph mapping; CHARMM topology atom types encode details
    # not represented by the generic graph. Stereo is then checked from the PDB coordinates.
    reference_graph = Chem.RWMol(reference)
    for bond in reference_graph.GetBonds():
        bond.SetBondType(Chem.BondType.SINGLE)
        bond.SetIsAromatic(False)
    reference_graph = reference_graph.GetMol()
    mapping = topology_graph.GetSubstructMatch(reference_graph, useChirality=False)
    assert len(mapping) == reference.GetNumAtoms(), "topology graph does not match CompoundForm"
    reverse_mapping = reference_graph.GetSubstructMatch(topology_graph, useChirality=False)
    assert len(reverse_mapping) == topology_graph.GetNumAtoms()
    assert len(atom_names) == reference.GetNumAtoms()

    coordinates = {}
    for line in structure_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and line[17:20] == "LIG":
            coordinates[line[12:16].strip()] = (
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            )
    assert set(atom_names) == set(coordinates), "PDB ligand atoms differ from topology atom names"

    coordinate_conformer = Chem.Conformer(reference.GetNumAtoms())
    for reference_index, topology_index in enumerate(mapping):
        atom_name = atom_names[topology_index]
        coordinate_conformer.SetAtomPosition(reference_index, coordinates[atom_name])
    mapped_reference = Chem.Mol(reference)
    mapped_reference.RemoveAllConformers()
    mapped_reference.AddConformer(coordinate_conformer)
    expected_cip = {
        atom.GetIdx(): atom.GetProp("_CIPCode")
        for atom in reference.GetAtoms()
        if atom.HasProp("_CIPCode")
    }
    Chem.AssignStereochemistryFrom3D(mapped_reference, confId=0, replaceExistingTags=True)
    Chem.AssignStereochemistry(mapped_reference, cleanIt=True, force=True)
    observed_cip = {
        atom.GetIdx(): atom.GetProp("_CIPCode")
        for atom in mapped_reference.GetAtoms()
        if atom.HasProp("_CIPCode")
    }
    assert expected_cip
    assert observed_cip == expected_cip, "PDB stereochemistry differs from form"
    return rdMolDescriptors.CalcMolFormula(reference), len(expected_cip)


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


@pytest.mark.skipif(
    not PYSCF_PYTHON, reason="set CADDSUITE_PYSCF_PYTHON for integrated QM composition"
)
def test_candidate_workflow_composes_md_qm_and_report_for_registered_form(
    tmp_path: Path,
) -> None:
    assert DATA_ROOT is not None
    assert GMX is not None
    assert MMPBSA is not None
    assert MMPBSA_PYTHON is not None
    source = (
        Path(STAGE_DATA_ROOT)
        if STAGE_DATA_ROOT is not None
        else Path(DATA_ROOT) / "projects/2M2D_LIG/gromacs"
    )
    from rdkit import Chem
    from rdkit.Chem import AllChem

    from caddsuite.adapters.qm.pyscf import PySCFAdapterParameters
    from caddsuite.chem.standardize import make_compound, standardize_smiles
    from caddsuite.contracts.base import ArtifactRef, EntityRef
    from caddsuite.contracts.qm import QMCalculation, QMModel, QMProtocol
    from caddsuite.contracts.registry import (
        CompoundForm,
        CompoundFormKind,
        Conformer,
    )

    assert PYSCF_PYTHON is not None
    compound_id, form_id = new_ulid(), new_ulid()
    pubchem_smiles = (
        "CC(C)[C@@H](C)/C=C/[C@@H](C)[C@H]1CC[C@@H]2[C@]1(C)CC[C@H]1"
        "[C@]23C=C[C@]2(C[C@@H](O)CC[C@]12C)OO3"
    )
    standardized = standardize_smiles(pubchem_smiles)
    assert standardized.identity.formula == "C28H44O3"
    identity_sources = (
        source / "toppar/LIG.itp",
        source / "step3_input.pdb",
    )
    identity_hashes = {path: _sha256(path) for path in identity_sources}
    formula, stereocentres = _assert_ligand_topology_matches_form(
        identity_sources[0], identity_sources[1], standardized.identity.canonical_smiles
    )
    assert formula == standardized.identity.formula
    assert stereocentres == 10
    form = CompoundForm(
        id=form_id,
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=standardized.identity.canonical_smiles,
        formal_charge=standardized.identity.formal_charge,
    )
    molecule = Chem.AddHs(Chem.MolFromSmiles(form.smiles))
    assert AllChem.EmbedMolecule(molecule, randomSeed=4815) == 0
    qm_sdf = tmp_path / "ergosterol_peroxide_qm.sdf"
    writer = Chem.SDWriter(str(qm_sdf))
    writer.write(molecule)
    writer.close()
    conformer_ref = ArtifactRef(
        artifact_id=new_ulid(),
        role="conformer_structure",
        sha256=_sha256(qm_sdf),
    )
    conformer = Conformer(
        id=new_ulid(),
        form_id=form.id,
        compound_id=compound_id,
        generator="ETKDGv3",
        seed=4815,
        structure=conformer_ref,
    )
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=form.id,
        compound_id=compound_id,
        geometry_source=EntityRef(kind="conformer", id=conformer.id),
        engine=_software("PySCF", "unknown", SoftwareKind.ENGINE),
        adapter=_software("caddsuite.qm.pyscf", "0.1.0", SoftwareKind.ADAPTER),
        model=QMModel(method="hf", basis="sto-3g"),
        protocol=QMProtocol.SINGLE_POINT,
        charge=form.formal_charge,
        multiplicity=1,
        requested_properties=("total_energy_Eh", "orbitals", "dipole_D"),
    )
    qm_parameters = PySCFAdapterParameters(
        python_executable=PYSCF_PYTHON,
        worker_source_directory=str(Path(__file__).resolve().parents[2] / "src"),
        memory_mb=3500,
        max_cycle=120,
        timeout_seconds=1800,
    ).model_dump()
    request, staged = _stage_request(
        source, tmp_path / "stage-input", compound_id=compound_id, form_id=form_id
    )
    source_paths = tuple(source / relative for relative in request.source_artifacts)
    source_hashes = {path: _sha256(path) for path in source_paths}

    processing_request = TrajectoryProcessingRequest(
        id=new_ulid(),
        simulation_id=request.simulation.id,
        compound_id=request.simulation.compound_id,
        form_id=request.simulation.form_id,
        topology=request.trajectory.topology,
        topology_format=request.topology_format,
        topology_has_connectivity=True,
        trajectory_format=request.trajectory_format,
        expected_atom_count=request.system.n_atoms,
        segments=(
            TrajectorySegmentInput(
                artifact=request.trajectory_artifact,
                output_start_time_ps=request.trajectory.time_range_ns[0] * 1000.0,
                n_frames=request.trajectory.n_frames,
                frame_interval_ps=request.trajectory.frame_interval_ps,
            ),
        ),
        transforms=(TrajectoryTransform.MAKE_MOLECULES_WHOLE,),
    )
    protein_index = request.system.selections["protein"].indices
    assert protein_index is not None
    static_sources = {
        path: artifact
        for path, artifact in request.source_artifacts.items()
        if path not in {"step5_1.tpr", "step5_1.gro", "analysis/combined_fit.xtc"}
    }
    energy_plan = BindingEnergyPlan(
        id=new_ulid(),
        trajectory_id=new_ulid(),
        accession=request.accession,
        system=request.system,
        parameterization=request.parameterization,
        simulation=request.simulation,
        topology_artifact=request.trajectory.topology,
        frames=request.frames,
        method=request.method,
        salt_concentration_M=request.salt_concentration_M,
        entropy=request.entropy,
        model=request.model,
        uncertainty=request.uncertainty,
        static_source_artifacts=static_sources,
        selection_groups=request.selection_groups,
        topology_format=request.topology_format,
        trajectory_format=request.trajectory_format,
    )
    protein_selection = request.system.selections["protein"]
    ligand_selection = request.system.selections["ligand"]
    analysis_plan = TrajectoryAnalysisPlan(
        id=new_ulid(),
        simulation_id=request.simulation.id,
        trajectory_id=new_ulid(),
        compound_id=request.simulation.compound_id,
        form_id=request.simulation.form_id,
        selections={
            "protein": protein_selection.model_copy(
                update={"indices": None, "description": "protein"}
            ),
            "ligand": ligand_selection.model_copy(
                update={"indices": None, "description": "resname LIG"}
            ),
        },
        metrics=(
            TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,
            TrajectoryMetric.PROTEIN_LIGAND_CONTACT_COUNT,
        ),
        end_time_ns=request.trajectory.time_range_ns[1],
        stride=100,
    )
    assert MDA_PYTHON is not None
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "PPARG processed trajectory analysis and MMGBSA",
            "inputs": {
                "processing_request": {"contract": "trajectory_processing_request/1.1"},
                "energy_plan": {"contract": "binding_energy_plan/1.0"},
                "analysis_plan": {"contract": "trajectory_analysis_plan/1.1"},
                "compound": {"contract": "compound/1.0"},
                "compound_form": {"contract": "compound_form/1.0"},
                "calculation": {"contract": "qm_calculation/1.2"},
                "conformer": {"contract": "conformer/1.1"},
            },
            "stages": [
                {
                    "id": "process",
                    "kind": "trajectory.process",
                    "engine": "gromacs",
                    "input_contracts": {"request": "trajectory_processing_request/1.1"},
                    "input_bindings": {"request": "$processing_request"},
                    "output_contract": "trajectory_processing_result/1.1",
                    "params": {
                        "engine_parameters": {
                            "gmx_executable": GMX,
                            "python_executable": sys.executable,
                            "output_group_atom_count": request.system.n_atoms,
                            "index_artifact": protein_index.model_dump(mode="json"),
                            "timeout_seconds": 3600,
                        }
                    },
                },
                {
                    "id": "trajectory_analysis",
                    "kind": "trajectory.analyze_processed",
                    "engine": "mdanalysis",
                    "needs": ["process"],
                    "input_contracts": {
                        "analysis_plan": "trajectory_analysis_plan/1.1",
                        "preprocessing": "trajectory_processing_result/1.1",
                    },
                    "input_bindings": {
                        "analysis_plan": "$analysis_plan",
                        "preprocessing": "process",
                    },
                    "output_contract": "trajectory_analysis_result/1.2",
                    "params": {
                        "engine_parameters": {
                            "python_executable": MDA_PYTHON,
                            "worker_script": str(
                                Path(__file__).resolve().parents[2]
                                / "src/caddsuite_worker/mdanalysis_metrics_worker.py"
                            ),
                            "timeout_seconds": 3600,
                        }
                    },
                },
                {
                    "id": "mmgbsa",
                    "kind": "binding_energy.analyze_processed",
                    "engine": "gmx_mmpbsa",
                    "needs": ["process"],
                    "input_contracts": {
                        "plan": "binding_energy_plan/1.0",
                        "preprocessing": "trajectory_processing_result/1.1",
                    },
                    "input_bindings": {
                        "plan": "$energy_plan",
                        "preprocessing": "process",
                    },
                    "output_contract": "binding_energy/1.3",
                    "params": {
                        "engine_parameters": {
                            "gmx_mmpbsa_executable": MMPBSA,
                            "gmx_executable": GMX,
                            "ambertools_bin": str(Path(MMPBSA).resolve().parent),
                            "python_executable": MMPBSA_PYTHON,
                            "worker_script": str(
                                Path(__file__).resolve().parents[2]
                                / "src/caddsuite_worker/gmx_mmpbsa_worker.py"
                            ),
                            "timeout_seconds": 3600,
                            "mpi_launch_retries": 0,
                        }
                    },
                },
                {
                    "id": "qm",
                    "kind": "quantum_chemistry",
                    "engine": "caddsuite.qm.pyscf",
                    "input_contracts": {
                        "calculation": "qm_calculation/1.2",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                    },
                    "input_bindings": {
                        "calculation": "$calculation",
                        "form": "$compound_form",
                        "conformer": "$conformer",
                    },
                    "output_contract": "qm_result/2.1",
                    "params": {"engine_parameters": qm_parameters},
                },
                {
                    "id": "report",
                    "kind": "report",
                    "needs": ["trajectory_analysis", "mmgbsa", "qm"],
                    "input_contracts": {
                        "compounds": "compound/1.0",
                        "compound_forms": "compound_form/1.0",
                        "conformers": "conformer/1.1",
                        "trajectory_results": "trajectory_analysis_result/1.2",
                        "binding_energy_results": "binding_energy/1.3",
                        "qm_calculations": "qm_calculation/1.2",
                        "qm_results": "qm_result/2.1",
                    },
                    "input_bindings": {
                        "compounds": "$compound",
                        "compound_forms": "$compound_form",
                        "conformers": "$conformer",
                        "trajectory_results": "trajectory_analysis",
                        "binding_energy_results": "mmgbsa",
                        "qm_calculations": "$calculation",
                        "qm_results": "qm",
                    },
                    "output_contract": "report_bundle/1.0",
                    "params": {
                        "formats": ["json", "html"],
                        "title": "PPARG ergosterol peroxide multi-evidence report",
                    },
                },
            ],
            "outputs": {
                "energy": "mmgbsa",
                "trajectory_analysis": "trajectory_analysis",
                "qm": "qm",
                "report": "report",
            },
        }
    )
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)

    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime",
        handlers=lambda services: registry.build_handlers(workflow, services),
    ) as runtime:
        qm_blob = runtime.services.artifacts.put_file(qm_sdf)
        with runtime.sessions.begin() as session:
            qm_row = register_blob(
                session,
                qm_blob,
                kind="qm_input",
                media_type="chemical/x-mdl-sdfile",
                original_name=qm_sdf.name,
            )
        conformer = conformer.model_copy(
            update={
                "structure": conformer.structure.model_copy(
                    update={"artifact_id": qm_row.id, "sha256": qm_blob.sha256}
                )
            }
        )
        for artifact in request.source_artifacts.values():
            staged_path = staged[str(artifact.artifact_id)]
            blob = runtime.services.artifacts.put_file(staged_path)
            assert blob.sha256 == artifact.sha256
            with runtime.sessions.begin() as session:
                register_blob(
                    session,
                    blob,
                    kind="workflow_input",
                    media_type="application/octet-stream",
                    original_name=artifact.role,
                    artifact_id=str(artifact.artifact_id),
                )
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="pparg-mmgbsa-composition", name="PPARG MMGBSA composition")
            session.add(project)
            session.flush()
            project_id = str(project.id)
            compound = make_compound(
                standardized,
                compound_id=compound_id,
                project_id=project_id,
                accession="CMP0001",
                name="ergosterol peroxide",
                original_text=pubchem_smiles,
                source="pubchem",
                location="PubChem CID 102004971",
            )
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-PPARG-MMGBSA-001",
                workflow_hash="e" * 64,
                config_hash="f" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id

        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={
                "processing_request": processing_request,
                "energy_plan": energy_plan,
                "analysis_plan": analysis_plan,
                "compound": compound,
                "compound_form": form,
                "calculation": calculation,
                "conformer": conformer,
            },
        )
        assert not outcome.failures
        assert len(outcome.tasks) == 5
        trajectory_result = outcome.outputs["trajectory_analysis"][0].value
        assert trajectory_result.simulation_id == request.simulation.id
        assert trajectory_result.compound_id == request.simulation.compound_id
        assert trajectory_result.form_id == request.simulation.form_id
        assert {metric.name for metric in trajectory_result.metrics} == {
            "mindist_protein_ligand",
            "contacts_protein_ligand",
        }
        result = outcome.outputs["energy"][0].value
        assert result.method is BindingEnergyMethod.MM_GBSA
        assert result.compound_id == request.simulation.compound_id
        assert result.form_id == request.simulation.form_id
        assert result.frames.n_used == 11
        assert result.temperature_K == pytest.approx(request.temperature_K)
        assert result.tool.version
        assert {"FINAL_RESULTS_MMGBSA.dat", "FINAL_RESULTS_MMGBSA.csv"} <= {
            Path(name).name for name in result.output_artifacts
        }
        assert result.log_artifacts
        qm_result = outcome.outputs["qm"][0].value
        assert qm_result.compound_id == compound.id == request.simulation.compound_id
        assert qm_result.form_id == form.id == request.simulation.form_id
        assert qm_result.orbitals is not None
        assert qm_result.orbitals.gap_eV > 0.0
        report = outcome.outputs["report"][0].value
        assert {artifact.format for artifact in report.artifacts} == {"json", "html"}
        assert all(
            artifact.artifact.sha256 and runtime.services.artifacts.verify(artifact.artifact.sha256)
            for artifact in report.artifacts
        )
        report_json_ref = next(item.artifact for item in report.artifacts if item.format == "json")
        report_json = json.loads(
            runtime.services.artifacts.path_for(report_json_ref.sha256 or "").read_text(
                encoding="utf-8"
            )
        )
        sections = {item["name"]: item for item in report_json["sections"]}
        registered = sections["compound"]["data"][0]
        assert registered["compound"]["id"] == str(compound.id)
        assert registered["forms"][0]["id"] == str(form.id)
        assert sections["input_structures"]["data"][0]["id"] == str(conformer.id)
        assert sections["trajectory_analyses"]["data"][0]["compound_id"] == str(compound.id)
        assert sections["trajectory_analyses"]["data"][0]["form_id"] == str(form.id)
        assert sections["mm_pbsa_gbsa"]["data"][0]["compound_id"] == str(compound.id)
        assert sections["mm_pbsa_gbsa"]["data"][0]["form_id"] == str(form.id)
        assert sections["quantum_properties"]["data"][0]["compound_id"] == str(compound.id)
        assert sections["quantum_properties"]["data"][0]["form_id"] == str(form.id)
        for artifact in (
            *result.output_artifacts.values(),
            *result.log_artifacts.values(),
            trajectory_result.raw_result,
            *trajectory_result.engine_artifacts.values(),
            *trajectory_result.log_artifacts.values(),
            *(metric.series for metric in trajectory_result.metrics),
        ):
            assert artifact.sha256 is not None
            assert runtime.services.artifacts.verify(artifact.sha256)
    assert source_hashes == {path: _sha256(path) for path in source_paths}
    assert identity_hashes == {path: _sha256(path) for path in identity_sources}
