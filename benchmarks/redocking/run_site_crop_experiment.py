from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem import rdMolAlign

from caddsuite.adapters.docking.vina import parse_vina_scores

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "benchmarks/redocking/pilot_v1"
BASELINE = PILOT / "runs/vina-pilot-v1-20260928"
CASES = {
    "5niu-8yz": (
        "5niu",
        "5niu-8yz_native.sdf",
        BASELINE
        / "preparation_jobs/prepare_5niu-8yz-01M3JMZHSBF9WNY74VZ1J5PBS0/prepared_receptor.pdb",
    ),
    "3ert-oht": ("3ert", "3ert-oht_native.sdf", PILOT / "prepared/3ert_protein.pdb"),
    "1m17-aq4": ("1m17", "1m17-aq4_native.sdf", PILOT / "prepared/1m17_protein.pdb"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], *, cwd: Path, stem: str, timeout: int = 300) -> dict[str, Any]:
    started = time.monotonic()
    # argv is an explicit, shell-free list built from configured executable paths and stage paths.
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)  # noqa: S603
    (cwd / f"{stem}.stdout.log").write_text(proc.stdout, encoding="utf-8")
    (cwd / f"{stem}.stderr.log").write_text(proc.stderr, encoding="utf-8")
    return {
        "argv": argv,
        "returncode": proc.returncode,
        "runtime_seconds": round(time.monotonic() - started, 3),
        "stdout_path": f"{stem}.stdout.log",
        "stderr_path": f"{stem}.stderr.log",
        "stdout_sha256": sha256(cwd / f"{stem}.stdout.log"),
        "stderr_sha256": sha256(cwd / f"{stem}.stderr.log"),
    }


def in_expanded_box(
    point: tuple[float, float, float], center: list[float], half: list[float], margin: float
) -> bool:
    return all(abs(point[axis] - center[axis]) <= half[axis] + margin for axis in range(3))


def select_residues(
    residue_atoms: dict[tuple[str, str, str, str], list[tuple[str, tuple[float, float, float]]]],
    center: list[float],
    half: list[float],
    margin: float,
) -> set[tuple[str, str, str, str]]:
    return {
        key
        for key, atoms in residue_atoms.items()
        if any(in_expanded_box(xyz, center, half, margin) for _, xyz in atoms)
    }


def calculate_site(molecule: Chem.Mol) -> tuple[list[float], list[float]]:
    heavy = Chem.RemoveHs(molecule)
    conformer = heavy.GetConformer()
    coords = [tuple(conformer.GetAtomPosition(i)) for i in range(heavy.GetNumAtoms())]
    center = [sum(point[axis] for point in coords) / len(coords) for axis in range(3)]
    size = [
        max(
            max(point[axis] for point in coords) - min(point[axis] for point in coords) + 10.0, 22.0
        )
        for axis in range(3)
    ]
    return center, size


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the separate site-local receptor compatibility experiment."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--engine-python", type=Path, default=os.environ.get("CADDSUITE_PDBFIXER_PYTHON")
    )
    parser.add_argument("--vina", type=Path, default=os.environ.get("CADDSUITE_VINA_EXECUTABLE"))
    args = parser.parse_args()
    if args.engine_python is None:
        parser.error("--engine-python or CADDSUITE_PDBFIXER_PYTHON is required")
    engine_python = Path(args.engine_python).resolve(strict=True)
    engine_dir = engine_python.parent
    vina = (
        Path(args.vina).resolve(strict=True)
        if args.vina
        else (engine_dir / "vina").resolve(strict=True)
    )
    if not args.output.is_absolute():
        output = (ROOT / args.output).resolve()
    else:
        output = args.output.resolve()
    if output.exists():
        parser.error(f"output must be a new directory: {output}")
    output.mkdir(parents=True)
    (output / "cases").mkdir()

    vina_version = subprocess.run(  # noqa: S603
        [str(vina), "--version"], capture_output=True, text=True, check=True, timeout=20
    ).stdout.strip()
    meeko_version = subprocess.run(  # noqa: S603
        [
            str(engine_python),
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('meeko'))",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    ).stdout.strip()
    baseline_summary = BASELINE / "summary.json"
    baseline_hash = sha256(baseline_summary)
    run_manifest = BASELINE / "RUN_SHA256SUMS"
    # Verify baseline inputs/results without launching a checksum utility from PATH.
    for line in run_manifest.read_text(encoding="ascii").splitlines():
        expected_hash, relative_path = line.split(maxsplit=1)
        relative_path = relative_path.lstrip(" *")
        artifact = (BASELINE / relative_path).resolve(strict=True)
        if artifact.is_symlink() or not artifact.is_relative_to(ROOT):
            raise RuntimeError(f"unsafe baseline manifest path: {relative_path}")
        if sha256(artifact) != expected_hash:
            raise RuntimeError(f"baseline hash mismatch: {relative_path}")

    report: dict[str, Any] = {
        "schema": "caddsuite.redocking-site-crop-experiment/1",
        "dataset_id": "redocking-pilot-v1",
        "experiment_id": output.name,
        "interpretation": (
            "Separate diagnostic protocol. It does not replace or amend the frozen v1 outcomes."
        ),
        "crop_rule": {
            "selection": (
                "retain complete residues when any input atom is within the docking axis-aligned "
                "box expanded by the Vina scoring cutoff"
            ),
            "expanded_by_A": 8.0,
            "cutoff_basis": (
                "upstream AutoDock Vina source ScoringFunction sets Vina potential cutoffs to "
                "8.0 A (see docs/validation/G-DOCK-10.md)"
            ),
            "limitations": (
                "cropping changes receptor context; no force-field minimization or residue "
                "repair is performed"
            ),
        },
        "baseline": {
            "summary_path": str(baseline_summary.relative_to(ROOT)),
            "summary_sha256": baseline_hash,
        },
        "software": {"vina": vina_version, "meeko": meeko_version},
        "protocol": {
            "seed": 42,
            "exhaustiveness": 16,
            "num_modes": 9,
            "energy_range_kcal_mol": 3.0,
            "cpu_cores": 2,
        },
        "cases": [],
    }

    for case_id, (pdb_id, ligand_filename, receptor_source) in CASES.items():
        case_dir = output / "cases" / case_id
        case_dir.mkdir()
        native_path = BASELINE / "ligands" / ligand_filename
        native = Chem.SDMolSupplier(str(native_path), removeHs=False)[0]
        if native is None or native.GetNumConformers() != 1:
            raise RuntimeError(f"invalid native ligand: {native_path}")
        center, size = calculate_site(native)
        source_lines = receptor_source.read_text(encoding="ascii").splitlines()
        residue_atoms: dict[
            tuple[str, str, str, str], list[tuple[str, tuple[float, float, float]]]
        ] = {}
        for line in source_lines:
            if not line.startswith(("ATOM  ", "HETATM")):
                continue
            key = (line[21:22], line[22:26], line[26:27], line[17:20])
            xyz = tuple(float(line[index : index + 8]) for index in (30, 38, 46))
            residue_atoms.setdefault(key, []).append((line, xyz))
        half = [axis / 2 for axis in size]

        selected = select_residues(residue_atoms, center, half, 8.0)
        cropped_lines = [
            line
            for line in source_lines
            if line.startswith(("ATOM  ", "HETATM"))
            and (line[21:22], line[22:26], line[26:27], line[17:20]) in selected
        ]
        receptor_crop = case_dir / "receptor_crop.pdb"
        receptor_crop.write_text("\n".join([*cropped_lines, "TER", "END"]) + "\n", encoding="ascii")
        receptor_pdbqt = case_dir / "receptor.pdbqt"
        receptor_json = case_dir / "receptor.json"
        receptor_call = run(
            [
                str(engine_python),
                str(engine_dir / "mk_prepare_receptor.py"),
                "--read_pdb",
                str(receptor_crop),
                "--write_pdbqt",
                str(receptor_pdbqt),
                "--write_json",
                str(receptor_json),
            ],
            cwd=case_dir,
            stem="meeko_receptor",
        )
        result: dict[str, Any] = {
            "case_id": case_id,
            "pdb_id": pdb_id.upper(),
            "receptor_source": str(receptor_source.relative_to(ROOT)),
            "receptor_source_sha256": sha256(receptor_source),
            "native_ligand_source": str(native_path.relative_to(ROOT)),
            "native_ligand_sha256": sha256(native_path),
            "site_center_A": center,
            "site_size_A": size,
            "source_residue_count": len(residue_atoms),
            "retained_residue_count": len(selected),
            "removed_residues": [list(key) for key in sorted(set(residue_atoms) - selected)],
            "receptor_crop_sha256": sha256(receptor_crop),
            "receptor_preparation": receptor_call,
            "status": "failed" if receptor_call["returncode"] else "prepared",
        }
        if receptor_call["returncode"] == 0:
            ligand_pdbqt = case_dir / "ligand.pdbqt"
            ligand_call = run(
                [
                    str(engine_python),
                    str(engine_dir / "mk_prepare_ligand.py"),
                    "--mol",
                    str(native_path),
                    "--out",
                    str(ligand_pdbqt),
                    "--charge_model",
                    "gasteiger",
                    "--add_index_map",
                ],
                cwd=case_dir,
                stem="meeko_ligand",
            )
            result["ligand_preparation"] = ligand_call
            if ligand_call["returncode"] == 0:
                poses_pdbqt = case_dir / "poses.pdbqt"
                vina_call = run(
                    [
                        str(vina),
                        "--receptor",
                        str(receptor_pdbqt),
                        "--ligand",
                        str(ligand_pdbqt),
                        "--center_x",
                        f"{center[0]:.8g}",
                        "--center_y",
                        f"{center[1]:.8g}",
                        "--center_z",
                        f"{center[2]:.8g}",
                        "--size_x",
                        f"{size[0]:.8g}",
                        "--size_y",
                        f"{size[1]:.8g}",
                        "--size_z",
                        f"{size[2]:.8g}",
                        "--exhaustiveness",
                        "16",
                        "--num_modes",
                        "9",
                        "--energy_range",
                        "3",
                        "--cpu",
                        "2",
                        "--seed",
                        "42",
                        "--out",
                        str(poses_pdbqt),
                    ],
                    cwd=case_dir,
                    stem="vina",
                    timeout=900,
                )
                result["docking"] = vina_call
                if vina_call["returncode"] == 0:
                    poses_sdf = case_dir / "poses.sdf"
                    export_call = run(
                        [
                            str(engine_python),
                            str(engine_dir / "mk_export.py"),
                            "--write_sdf",
                            str(poses_sdf),
                            str(poses_pdbqt),
                        ],
                        cwd=case_dir,
                        stem="meeko_export",
                    )
                    result["pose_export"] = export_call
                    if export_call["returncode"] == 0:
                        molecules = [
                            mol
                            for mol in Chem.SDMolSupplier(str(poses_sdf), removeHs=False)
                            if mol is not None
                        ]
                        native_heavy = Chem.RemoveHs(native)
                        pose_results = []
                        for rank, docked in enumerate(molecules, start=1):
                            if docked.GetNumHeavyAtoms() != native_heavy.GetNumHeavyAtoms():
                                raise RuntimeError(
                                    f"{case_id} pose {rank} heavy-atom count mismatch"
                                )
                            rmsd = rdMolAlign.CalcRMS(
                                Chem.RemoveHs(docked), native_heavy, maxMatches=100000
                            )
                            scores = parse_vina_scores(
                                poses_pdbqt.read_text(encoding="utf-8"),
                                expected_modes=len(molecules),
                            )
                            pose_results.append(
                                {
                                    "rank": rank,
                                    "score_kcal_mol": scores[rank - 1].affinity_kcal_mol,
                                    "symmetry_corrected_no_fit_rmsd_A": round(rmsd, 4),
                                    "heavy_atom_count": docked.GetNumHeavyAtoms(),
                                }
                            )
                        result["poses"] = pose_results
                        result["status"] = "docked"
                    else:
                        result["status"] = "pose_export_failed"
                else:
                    result["status"] = "docking_failed"
            else:
                result["status"] = "ligand_preparation_failed"
        report["cases"].append(result)
        (case_dir / "case_result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    report["outcomes"] = {
        "case_count": len(report["cases"]),
        "meeko_prepared_count": sum(
            c["receptor_preparation"]["returncode"] == 0 for c in report["cases"]
        ),
        "docked_count": sum(c["status"] == "docked" for c in report["cases"]),
        "top_pose_success_count": sum(
            bool(c.get("poses")) and c["poses"][0]["symmetry_corrected_no_fit_rmsd_A"] < 2.0
            for c in report["cases"]
        ),
    }
    report_path = output / "summary.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum_files = sorted(
        path for path in output.rglob("*") if path.is_file() and path.name != "SHA256SUMS"
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(output)}\n" for path in checksum_files),
        encoding="ascii",
    )
    print(json.dumps(report["outcomes"], sort_keys=True))
    print(f"summary={report_path}")
    print(f"summary_sha256={sha256(report_path)}")
    return 0 if report["outcomes"]["case_count"] == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
