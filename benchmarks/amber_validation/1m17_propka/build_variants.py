from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from caddsuite.adapters.system_builders.amber_handler import AmberTLeapBuilderHandler
from caddsuite.adapters.system_builders.amber_tleap import AmberTLeapBuilderAdapter
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildRequest
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade

ROOT = Path(__file__).resolve().parents[3]
PROTEIN = ROOT / "benchmarks/redocking/pilot_v1/prepared/1m17_protein.pdb"
LIGAND = ROOT / "benchmarks/redocking/pilot_v1/runs/vina-pilot-v1-20260928/ligands/1m17-aq4_native.sdf"
ASSEMBLY = ROOT / "benchmarks/amber_validation/1m17_propka/protein_ligand/input_complex.pdb"
HISTIDINES = ("A:749:_", "A:781:_", "A:811:_", "A:826:_", "A:846:_", "A:864:_", "A:869:_", "A:964:_")
VARIANTS = {
    "all_hid": {},
    "hip_a781": {"A:781:_": "HIP"},
    "hip_a864": {"A:864:_": "HIP"},
    "hip_a781_a864": {"A:781:_": "HIP", "A:864:_": "HIP"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build controlled 1M17/AQ4 Amber histidine variants.")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--amber-home", type=Path, default=Path("/home/sridhar/miniconda3/envs/gmxMMPBSA"))
    parser.add_argument("--gromacs", type=Path, default=Path("/home/sridhar/miniconda3/envs/gmx/bin/gmx"))
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    if data_root.exists() and any(data_root.iterdir()):
        raise SystemExit(f"refusing non-empty output root: {data_root}")
    data_root.mkdir(parents=True, exist_ok=True)

    database = data_root / "platform.sqlite"
    upgrade(database)
    engine = create_db_engine(database)
    sessions = make_session_factory(engine)
    store = ArtifactStore(data_root / "artifacts")
    artifact_meta = {}
    for label, path, kind, media in (
        ("protein", PROTEIN, "prepared_receptor_pdb", "chemical/x-pdb"),
        ("ligand", LIGAND, "normalized_pose_sdf", "chemical/x-mdl-sdfile"),
        ("assembly", ASSEMBLY, "coordinate_complex", "chemical/x-pdb"),
    ):
        blob = store.put_file(path)
        with sessions.begin() as session:
            row = register_blob(
                session,
                blob,
                kind=kind,
                media_type=media,
                original_name=path.name,
            )
            artifact_meta[label] = {
                "id": row.id,
                "sha256": blob.sha256,
                "path": str(path),
                "kind": kind,
            }

    refs = {
        key: ArtifactRef(
            artifact_id=artifact_meta[key]["id"],
            role=artifact_meta[key]["kind"],
            sha256=artifact_meta[key]["sha256"],
        )
        for key in ("protein", "ligand", "assembly")
    }
    protein_count = sum(1 for line in PROTEIN.read_text(encoding="ascii").splitlines() if line.startswith("ATOM  "))
    from rdkit import Chem
    mol = next((item for item in Chem.SDMolSupplier(str(LIGAND), removeHs=False) if item is not None), None)
    if mol is None:
        raise SystemExit("AQ4 SDF could not be parsed")
    ligand_count = mol.GetNumAtoms()
    ligand_heavy = mol.GetNumHeavyAtoms()
    complex_id, compound_id, form_id, target_id, pose_id = (new_ulid() for _ in range(5))
    complex_model = Complex(
        id=complex_id,
        compound_id=compound_id,
        form_id=form_id,
        target_id=target_id,
        structure_id=new_ulid(),
        prepared_receptor_id=new_ulid(),
        docking_run_id=new_ulid(),
        pose_id=pose_id,
        protein=refs["protein"],
        ligand=refs["ligand"],
        assembled=refs["assembly"],
        protein_atom_count=protein_count,
        ligand_atom_count=ligand_count,
        ligand_heavy_atom_count=ligand_heavy,
        coordinate_fidelity_max_dev_A=0.0,
    )
    adapter = AmberTLeapBuilderAdapter(
        amber_prefix=args.amber_home,
        gromacs_executable=args.gromacs,
        worker_script=ROOT / "src/caddsuite_worker/amber_tleap_worker.py",
    )
    handler = AmberTLeapBuilderHandler(
        adapter=adapter,
        work_root=data_root / "jobs",
        log_root=data_root / "logs",
        engine_version="AmberTools 23.6 / ParmEd / configured GROMACS; exact worker report retained",
        executor=LocalExecutor(store, sessions),
        artifact_store=store,
        sessions=sessions,
    )
    build_root = data_root / "variant_reports"
    build_root.mkdir()
    for variant, charged in VARIANTS.items():
        state_map = {key: "HID" for key in HISTIDINES}
        state_map.update(charged)
        request = SystemBuildRequest(
            id=new_ulid(),
            complex_id=complex_id,
            compound_id=compound_id,
            form_id=form_id,
            target_id=target_id,
            pose_id=pose_id,
            source_artifacts={
                "inputs/protein.pdb": refs["protein"],
                "inputs/ligand.sdf": refs["ligand"],
            },
            selections={"protein": "Protein", "ligand": "LIG"},
            mode="build",
            parameters={
                "protein_artifact_path": "inputs/protein.pdb",
                "ligand_artifact_path": "inputs/ligand.sdf",
                "protein_ff": "ff14SB",
                "ligand_method": "GAFF2",
                "ligand_charge_model": "AM1-BCC",
                "ligand_net_charge": 0,
                "protein_ph": 7.4,
                "histidine_states": state_map,
                "disulfide_bonds": [],
                "water_model": "TIP3P",
                "ion_parameters": "Joung-Cheatham TIP3P",
                "ion_policy": "neutralize_only",
                "box_padding_A": 8.0,
                "output_format": "amber",
            },
        )
        invocation = SimpleNamespace(
            task=SimpleNamespace(stage_id=f"amber_{variant}", params={}),
            inputs={"system_build_request": (request,), "complex": (complex_model,)},
        )
        result = handler.execute(invocation)
        raw = result.raw_artifacts["amber_outputs/worker_result.json"]
        report = json.loads(store.path_for(raw.sha256).read_text(encoding="utf-8"))
        payload = {
            "variant": variant,
            "request": request.model_dump(mode="json"),
            "normalized_result": result.model_dump(mode="json"),
            "worker_report": report,
            "raw_artifacts": {
                key: value.model_dump(mode="json") for key, value in result.raw_artifacts.items()
            },
            "normalized_artifacts": {
                key: value.model_dump(mode="json") for key, value in result.normalized_artifacts.items()
            },
        }
        (build_root / f"{variant}.json").write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"{variant}: built_atoms={result.system.n_atoms} "
            f"protein_atoms={result.system.selections['protein'].n_atoms} "
            f"ligand_atoms={result.system.selections['ligand'].n_atoms} "
            f"net_charge={report.get('system_charge_e')} "
            f"worker_status={report.get('status')}"
        )


if __name__ == "__main__":
    main()
