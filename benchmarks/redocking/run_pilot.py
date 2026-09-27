"""Execute the pinned redocking pilot through the CADD Suite workflow and Vina adapter."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict, cast

from benchmarks.redocking.native_ligand import native_ligand_from_mmcif
from rdkit import Chem
from rdkit.Chem import rdMolAlign, rdMolDescriptors

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.docking import DockingResult
from caddsuite.contracts.registry import (
    ChemicalIdentity,
    Compound,
    CompoundForm,
    CompoundFormKind,
    Conformer,
    InputRecord,
    StandardizationRecord,
    StandardizationStep,
)
from caddsuite.contracts.structure import BindingSite, BindingSiteMethod, Structure, StructureSource
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, WorkflowRunRow
from caddsuite.storage.provenance_graph import attempt_lineage
from caddsuite.workflow.definition import WorkflowDefinition


class PoseMetric(TypedDict):
    rank: int
    score_kcal_mol: float
    symmetry_corrected_no_fit_rmsd_A: float
    structure_sha256: str | None
    raw_pose_sha256: str | None


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "benchmarks/redocking/pilot_v1"


def _native_5niu() -> Chem.Mol:
    native_path = ROOT / "tests/data/golden/docking_g1/receptors/5NIU_ref_ligand.pdb"
    ideal_path = ROOT / "tests/data/golden/docking_g1/receptors/8YZ_ideal.sdf"
    native = Chem.MolFromPDBFile(str(native_path), removeHs=False, sanitize=True)
    ideal = Chem.SDMolSupplier(str(ideal_path), removeHs=False)[0]
    if native is None or ideal is None:
        raise ValueError("Could not load frozen 5NIU/8YZ native ligand fixtures")
    native, ideal = Chem.RemoveHs(native), Chem.RemoveHs(ideal)
    lines = [
        line for line in native_path.read_text().splitlines() if line.startswith(("ATOM", "HETATM"))
    ]
    names = [line[12:16].strip() for line in lines]
    cif_lines = (ROOT / "tests/data/golden/structure_g1/5NIU.cif").read_text().splitlines()
    start = next(i for i, line in enumerate(cif_lines) if line.strip() == "_chem_comp_atom.comp_id")
    ccd_names = []
    for line in cif_lines[start + 5 :]:
        fields = line.split()
        if not fields or line.startswith("#"):
            break
        if fields[0] == "8YZ" and fields[2] != "H":
            ccd_names.append(fields[1])
    if names != ccd_names or native.GetNumAtoms() != ideal.GetNumAtoms():
        raise ValueError("5NIU native ligand names/order differ from the pinned CCD graph")
    if tuple(a.GetAtomicNum() for a in native.GetAtoms()) != tuple(  # type: ignore[no-untyped-call]
        a.GetAtomicNum()
        for a in ideal.GetAtoms()  # type: ignore[no-untyped-call]
    ):
        raise ValueError("5NIU native ligand element order differs from the CCD ideal SDF")
    conf_native, conf_ideal = native.GetConformer(), ideal.GetConformer()
    for i in range(ideal.GetNumAtoms()):
        conf_ideal.SetAtomPosition(i, conf_native.GetAtomPosition(i))
    return Chem.AddHs(ideal, addCoords=True)


def _workflow(vina: Path, engine_dir: Path, python: Path) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Pinned native redocking pilot",
            "inputs": {
                "compound": {"contract": "compound/1.0"},
                "form": {"contract": "compound_form/1.0"},
                "conformer": {"contract": "conformer/1.1"},
                "receptor": {"contract": "prepared_receptor/1.0"},
                "target_structure": {"contract": "structure/1.0"},
                "site": {"contract": "binding_site/1.0"},
            },
            "stages": [
                {
                    "id": "dock",
                    "kind": "docking",
                    "engine": "vina",
                    "for_each": "compound",
                    "input_contracts": {
                        "compound": "compound/1.0",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                        "receptor": "prepared_receptor/1.0",
                        "target_structure": "structure/1.0",
                        "site": "binding_site/1.0",
                    },
                    "input_bindings": {
                        key: f"${key}"
                        for key in (
                            "compound",
                            "form",
                            "conformer",
                            "receptor",
                            "target_structure",
                            "site",
                        )
                    },
                    "output_contract": DockingResult.schema_id(),
                    "params": {
                        "engine_parameters": {
                            "vina_executable": str(vina),
                            "meeko_python": str(python),
                            "mk_prepare_receptor": str(engine_dir / "mk_prepare_receptor.py"),
                            "mk_prepare_ligand": str(engine_dir / "mk_prepare_ligand.py"),
                            "mk_export": str(engine_dir / "mk_export.py"),
                            "memory_MiB": 4096,
                        },
                        "docking_parameters": {
                            "exhaustiveness": 16,
                            "num_modes": 9,
                            "energy_range_kcal_mol": 3.0,
                            "cpu_cores": 2,
                            "seed": 42,
                        },
                    },
                }
            ],
            "outputs": {"result": "dock"},
        }
    )


def _worker_package_version(python: Path, package: str) -> str:
    code = f"import importlib.metadata as m; print(m.version({package!r}))"
    completed = subprocess.run(  # noqa: S603 - executable is explicit configured env Python
        [str(python), "-c", code], check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def main() -> int:
    python_text = os.environ.get("CADDSUITE_PDBFIXER_PYTHON")
    if not python_text:
        raise SystemExit("Set CADDSUITE_PDBFIXER_PYTHON to the isolated PDBFixer/Meeko environment")
    python = Path(python_text).resolve(strict=True)
    engine_dir = python.parent
    vina = engine_dir / "vina"
    if not vina.is_file():
        raise SystemExit(f"Vina executable not found beside engine Python: {vina}")
    output_text = os.environ.get("CADDSUITE_REDOCKING_RUN_DIR")
    if not output_text:
        raise SystemExit("Set CADDSUITE_REDOCKING_RUN_DIR to a new persistent run directory")
    output = Path(output_text).expanduser()
    output = output.resolve()
    resume = os.environ.get("CADDSUITE_REDOCKING_RESUME") == "1"
    output.mkdir(parents=True, exist_ok=resume)
    data_root = output / "platform"
    git_executable = shutil.which("git")
    if git_executable is None:
        raise SystemExit("git executable required to capture run provenance")
    git_commit = subprocess.run(  # noqa: S603 - executable resolved via shutil.which
        [git_executable, "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    versions = {
        "vina": subprocess.run(  # noqa: S603 - resolved executable, fixed version argument
            [str(vina), "--version"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "meeko": _worker_package_version(python, "meeko"),
        "pdbfixer": _worker_package_version(python, "pdbfixer"),
        "openmm": _worker_package_version(python, "openmm"),
        "rdkit": importlib.metadata.version("rdkit"),
    }
    workflow = _workflow(vina, engine_dir, python)
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)
    runtime = LocalWorkflowRuntime.open(
        data_root=data_root,
        handlers=lambda services: registry.build_handlers(workflow, services),
    )
    sessions, store = runtime.sessions, runtime.services.artifacts
    with sessions() as session:
        project_row = session.query(ProjectRow).filter_by(slug="redocking-pilot").first()
        project_id = project_row.id if project_row is not None else new_ulid()
    if project_row is None:
        with sessions.begin() as session:
            session.add(
                ProjectRow(id=project_id, slug="redocking-pilot", name="Redocking pilot v1")
            )
    results = []
    try:
        for case in json.loads((PILOT / "manifest.json").read_text())["cases"]:
            case_id = case["case_id"]
            case_output = output / f"{case_id}.json"
            if case_output.is_file():
                saved = json.loads(case_output.read_text())
                if saved.get("normalized_result"):
                    results.append(saved)
                    print(json.dumps({"case_id": case_id, "status": "reused_completed_result"}))
                    continue
            input_path = (PILOT / case["structure_path"]).resolve()
            input_blob = store.put_file(input_path)
            with sessions.begin() as session:
                input_row = register_blob(
                    session,
                    input_blob,
                    kind="raw_structure_mmcif",
                    media_type="chemical/x-mmcif",
                    original_name=input_path.name,
                )
                raw_ref = ArtifactRef(
                    artifact_id=input_row.id, role="raw_structure_mmcif", sha256=input_blob.sha256
                )
            target_id = new_ulid()
            structure = Structure(
                id=new_ulid(),
                target_id=target_id,
                source=StructureSource.RCSB,
                source_id=case["pdb_id"],
                entity_sequences={},
                raw=raw_ref,
            )
            # Invoke the registered stage handler directly while preserving its worker request,
            # response, outputs, and content-addressed artifacts in the project store.
            from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler

            fixer = PDBFixerPreparationHandler(
                python_executable=python,
                worker_script=ROOT / "src/caddsuite_worker/pdbfixer_worker.py",
                work_root=output / "preparation_jobs",
                log_root=output / "preparation_logs",
                engine_version=f"PDBFixer {versions['pdbfixer']} / OpenMM {versions['openmm']}",
                executor=runtime.services.executor,
                artifact_store=store,
                sessions=sessions,
            )
            prepared = fixer.execute(
                cast(
                    Any,
                    SimpleNamespace(
                        task=SimpleNamespace(
                            stage_id=f"prepare_{case_id}",
                            params={
                                "selected_chain_ids": [case["protein_auth_chain"]],
                                "ph": 7.4,
                                "fill_internal_gaps": True,
                                "keep_water": False,
                            },
                        ),
                        inputs={"structure": (structure,)},
                    ),
                )
            )

            if case_id == "5niu-8yz":
                molecule = _native_5niu()
            else:
                lig = case["ligand"]
                molecule = native_ligand_from_mmcif(
                    input_path,
                    PILOT / lig["ideal_graph_path"],
                    component_id=lig["ccd_id"],
                    auth_chain=lig["auth_chain"],
                    auth_seq_id=lig["auth_seq_id"],
                    label_asym_id=lig.get("label_asym_id"),
                )
            parent = Chem.RemoveHs(molecule)
            smiles = Chem.MolToSmiles(parent, canonical=True, isomericSmiles=True)
            inchi = Chem.MolToInchi(parent)  # type: ignore[no-untyped-call]
            ligand_path = output / "ligands" / f"{case_id}_native.sdf"
            ligand_path.parent.mkdir(parents=True, exist_ok=True)
            with Chem.SDWriter(str(ligand_path)) as writer:
                writer.write(molecule)
            ligand_blob = store.put_file(ligand_path)
            with sessions.begin() as session:
                ligand_row = register_blob(
                    session,
                    ligand_blob,
                    kind="ligand_conformer_sdf",
                    media_type="chemical/x-mdl-sdfile",
                    original_name=ligand_path.name,
                )
                ligand_ref = ArtifactRef(
                    artifact_id=ligand_row.id,
                    role="ligand_conformer_sdf",
                    sha256=ligand_blob.sha256,
                )
            compound_id = new_ulid()
            compound = Compound(
                id=compound_id,
                accession=f"CMP{len(results) + 1:04d}",
                project_id=project_id,
                name=f"Native {case['ligand']['ccd_id']} {case['pdb_id']}",
                input_record=InputRecord(source="legacy_import", original_text=smiles),
                parent=ChemicalIdentity(
                    canonical_smiles=smiles,
                    inchi=inchi,
                    inchikey=Chem.MolToInchiKey(parent),  # type: ignore[no-untyped-call]
                    formula=rdMolDescriptors.CalcMolFormula(parent),
                    formal_charge=Chem.GetFormalCharge(parent),
                    heavy_atom_count=parent.GetNumHeavyAtoms(),
                ),
                standardization=StandardizationRecord(
                    policy="native_reference_ligand",
                    steps=(
                        StandardizationStep(
                            operation="CCD_graph_to_crystal_coordinates", changed=False
                        ),
                    ),
                    toolkit=SoftwareRef(
                        name="RDKit",
                        version=versions["rdkit"],
                        kind=SoftwareKind.LIBRARY,
                        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
                    ),
                ),
            )
            form = CompoundForm(
                id=new_ulid(),
                compound_id=compound_id,
                kind=CompoundFormKind.PARENT_NEUTRAL,
                smiles=smiles,
                formal_charge=Chem.GetFormalCharge(parent),
            )
            conformer = Conformer(
                id=new_ulid(),
                form_id=form.id,
                compound_id=compound_id,
                generator=(
                    "CCD ideal graph + native crystal heavy-atom coordinates + RDKit hydrogens"
                ),
                selected_by="redocking-pilot-v1",
                structure=ligand_ref,
            )
            conf = parent.GetConformer()
            coords = [conf.GetAtomPosition(i) for i in range(parent.GetNumAtoms())]
            xyz = [[float(p.x), float(p.y), float(p.z)] for p in coords]
            center = tuple(sum(p[axis] for p in xyz) / len(xyz) for axis in range(3))
            spans = tuple(
                max(p[axis] for p in xyz) - min(p[axis] for p in xyz) for axis in range(3)
            )
            size = tuple(max(span + 10.0, 22.0) for span in spans)
            site = BindingSite(
                id=new_ulid(),
                target_id=target_id,
                method=BindingSiteMethod.COORDINATES,
                center_A=center,
                size_A=size,
                volume_A3=size[0] * size[1] * size[2],
                source_structure=raw_ref,
            )
            accession = f"RUN-{case_id.upper()}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            with sessions.begin() as session:
                run = WorkflowRunRow(
                    project_id=project_id,
                    accession=accession,
                    workflow_hash=hashlib.sha256(
                        json.dumps(workflow.model_dump(mode="json"), sort_keys=True).encode()
                    ).hexdigest(),
                    config_hash=hashlib.sha256(
                        json.dumps(workflow.model_dump(mode="json"), sort_keys=True).encode()
                    ).hexdigest(),
                    status="running",
                )
                session.add(run)
                session.flush()
                run_id = run.id
            outcome = runtime.run(
                compiled,
                run_id=run_id,
                inputs={
                    "compound": (compound,),
                    "form": (form,),
                    "conformer": (conformer,),
                    "receptor": (prepared,),
                    "target_structure": (structure,),
                    "site": (site,),
                },
            )
            if outcome.failures:
                with sessions() as session:
                    failed_attempt_row = (
                        session.query(TaskAttemptRow)
                        .order_by(TaskAttemptRow.started_at.desc())
                        .first()
                    )
                failed_provenance = None
                if failed_attempt_row is not None:
                    from caddsuite.contracts.execution import TaskAttempt

                    failed_attempt = TaskAttempt.model_validate(failed_attempt_row.payload)
                    failed_provenance = attempt_lineage(sessions, str(failed_attempt.id))
                    (output / "provenance").mkdir(exist_ok=True)
                    (output / "provenance" / f"{case_id}.json").write_text(
                        json.dumps(failed_provenance, indent=2, sort_keys=True) + "\n"
                    )
                failed = {
                    "case_id": case_id,
                    "pdb_id": case["pdb_id"],
                    "ccd_id": case["ligand"]["ccd_id"],
                    "status": "failed",
                    "target_A": 2.0,
                    "primary_success": False,
                    "input_structure_sha256": raw_ref.sha256,
                    "native_ligand_sha256": ligand_ref.sha256,
                    "prepared_receptor_pdb_sha256": prepared.artifacts[
                        "prepared_structure_pdb"
                    ].sha256,
                    "provenance_artifact": failed_provenance is not None,
                    "failures": [
                        {
                            "stage_id": failure.stage_id,
                            "state": failure.state.value,
                            "error": failure.error,
                        }
                        for failure in outcome.failures
                    ],
                }
                case_output.write_text(json.dumps(failed, indent=2, sort_keys=True) + "\n")
                results.append(failed)
                print(json.dumps(failed, sort_keys=True))
                continue
            result = outcome.outputs["result"][0].value
            if not isinstance(result, DockingResult) or not result.poses:
                raise RuntimeError(f"{case_id} produced no normalized docking poses")
            native_heavy = Chem.RemoveHs(parent)
            pose_rows: list[PoseMetric] = []
            for pose in result.poses:
                path = store.path_for(pose.structure.sha256 or "")
                docked = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=True)
                if docked is None or docked.GetNumHeavyAtoms() != native_heavy.GetNumHeavyAtoms():
                    raise RuntimeError(
                        f"{case_id} pose {pose.rank} could not be compared to the native ligand"
                    )
                rmsd = rdMolAlign.CalcRMS(Chem.RemoveHs(docked), native_heavy, maxMatches=100000)
                if not math.isfinite(rmsd):
                    raise RuntimeError(f"{case_id} pose {pose.rank} has non-finite RMSD")
                pose_rows.append(
                    {
                        "rank": pose.rank,
                        "score_kcal_mol": float(pose.score.value),
                        "symmetry_corrected_no_fit_rmsd_A": round(rmsd, 4),
                        "structure_sha256": pose.structure.sha256,
                        "raw_pose_sha256": pose.raw.sha256,
                    }
                )
            with sessions() as session:
                attempt_row = (
                    session.query(TaskAttemptRow).order_by(TaskAttemptRow.started_at.desc()).first()
                )
            provenance = None
            if attempt_row is not None:
                from caddsuite.contracts.execution import TaskAttempt

                attempt = TaskAttempt.model_validate(attempt_row.payload)
                provenance = attempt_lineage(sessions, str(attempt.id))
                (output / "provenance").mkdir(exist_ok=True)
                (output / "provenance" / f"{case_id}.json").write_text(
                    json.dumps(provenance, indent=2, sort_keys=True) + "\n"
                )
            case_result = {
                "case_id": case_id,
                "status": "succeeded",
                "pdb_id": case["pdb_id"],
                "ccd_id": case["ligand"]["ccd_id"],
                "target_A": 2.0,
                "primary_success": pose_rows[0]["symmetry_corrected_no_fit_rmsd_A"] < 2.0,
                "engine": result.run.engine.model_dump(mode="json"),
                "parameters": result.run.params,
                "site_center_A": center,
                "site_size_A": size,
                "poses": pose_rows,
                "normalized_result": result.model_dump(mode="json"),
                "provenance_artifact": provenance is not None,
            }
            (output / f"{case_id}.json").write_text(
                json.dumps(case_result, indent=2, sort_keys=True) + "\n"
            )
            results.append(case_result)
            print(
                json.dumps(
                    {
                        "case_id": case_id,
                        "poses": pose_rows,
                        "primary_success": case_result["primary_success"],
                    },
                    sort_keys=True,
                )
            )
        case_count = len(json.loads((PILOT / "manifest.json").read_text())["cases"])
        successes = sum(
            item.get("status", "succeeded" if item.get("normalized_result") else "failed")
            == "succeeded"
            and item["primary_success"]
            for item in results
        )
        summary = {
            "schema": "caddsuite.redocking-run/1",
            "dataset_id": "redocking-pilot-v1",
            "created_utc": datetime.now(UTC).isoformat(),
            "git_commit": git_commit,
            "runner_sha256": runner_sha256,
            "software": versions,
            "protocol": {
                "seed": 42,
                "exhaustiveness": 16,
                "num_modes": 9,
                "energy_range_kcal_mol": 3.0,
                "cpu_cores": 2,
                "protein_ph": 7.4,
                "water": "removed",
                "internal_gap_filling": True,
            },
            "cases": results,
            "successes": successes,
            "case_count": case_count,
            "success_fraction": successes / case_count,
            "limitations": [
                "Small three-complex pilot only.",
                "RMSD is a pose-recovery diagnostic, not binding affinity.",
                "1M17 includes a modeled internal receptor gap; both new cases have "
                "unresolved termini.",
            ],
        }
        (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        print(f"Run artifacts: {output}")
        return 0
    finally:
        runtime.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
