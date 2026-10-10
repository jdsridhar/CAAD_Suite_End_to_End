"""Execute locked preregistered redocking benchmark attempts with resource sidecar."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from rdkit import Chem
from rdkit.Chem import rdMolAlign

try:
    from benchmarks.redocking.curate_candidates import _atom_rows, _choose_protein_atoms
    from benchmarks.redocking.native_ligand import native_ligand_from_mmcif
except ImportError:
    from curate_candidates import _atom_rows, _choose_protein_atoms  # type: ignore[no-redef]
    from native_ligand import native_ligand_from_mmcif  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def parse_time_output(stderr_text: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    time_lines: list[str] = []
    other_lines: list[str] = []
    for line in stderr_text.splitlines():
        if "\t" in line and ":" in line:
            time_lines.append(line)
            key, val = line.strip().split(":", 1)
            key = key.strip()
            val = val.strip()
            if key == "User time (seconds)":
                metrics["user_time_seconds"] = float(val)
            elif key == "System time (seconds)":
                metrics["system_time_seconds"] = float(val)
            elif key == "Percent of CPU this job got":
                metrics["cpu_percent"] = int(val.rstrip("%"))
            elif key == "Elapsed (wall clock) time (h:mm:ss or m:ss)":
                metrics["elapsed_wall_clock"] = val
                parts = val.split(":")
                if len(parts) == 2:
                    seconds = float(parts[0]) * 60 + float(parts[1])
                elif len(parts) == 3:
                    seconds = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                else:
                    seconds = float(val)
                metrics["wall_time_seconds"] = seconds
            elif key == "Maximum resident set size (kbytes)":
                metrics["peak_rss_kbytes"] = int(val)
                metrics["peak_rss_mib"] = round(int(val) / 1024.0, 2)
            elif key == "Major (requiring I/O) page faults":
                metrics["major_page_faults"] = int(val)
            elif key == "Minor (reclaiming a frame) page faults":
                metrics["minor_page_faults"] = int(val)
            elif key == "Voluntary context switches":
                metrics["voluntary_context_switches"] = int(val)
            elif key == "Involuntary context switches":
                metrics["involuntary_context_switches"] = int(val)
        else:
            other_lines.append(line)
    return {
        "metrics": metrics,
        "time_summary": "\n".join(time_lines),
        "clean_stderr": "\n".join(other_lines),
    }


def run_command(
    argv: list[str],
    *,
    cwd: Path,
    stem: str,
    timeout: int = 1800,
) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(  # noqa: S603
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    stdout_path = cwd / f"{stem}.stdout.log"
    stderr_path = cwd / f"{stem}.stderr.log"
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    return {
        "argv": argv,
        "returncode": proc.returncode,
        "runtime_seconds": round(time.monotonic() - started, 3),
        "stdout_path": stdout_path.name,
        "stderr_path": stderr_path.name,
        "stdout_sha256": _sha256(stdout_path),
        "stderr_sha256": _sha256(stderr_path),
    }


def ensure_ccd_ideal_sdf(component_id: str, cache_dir: Path) -> Path:
    target_path = cache_dir / f"{component_id}_ideal.sdf"
    if target_path.exists():
        return target_path
    url = f"https://files.rcsb.org/ligands/download/{component_id}_ideal.sdf"
    req = urllib.request.Request(url, headers={"User-Agent": "CADD-Suite/0.1"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                data = resp.read()
                target_path.write_bytes(data)
                return target_path
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    raise RuntimeError(f"Failed to download CCD ideal SDF for {component_id}")


def run_attempt(
    manifest_path: Path,
    case_id: str,
    seed: int,
    output_dir: Path,
    *,
    vina_path: Path,
    engine_python: Path,
    structure_cache: Path,
    exhaustiveness: int = 16,
    num_modes: int = 9,
    energy_range: float = 3.0,
    cpu_cores: int = 2,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = next((c for c in manifest.get("cases", []) if c.get("case_id") == case_id), None)
    if case is None:
        raise ValueError(f"Case {case_id} not found in manifest {manifest_path}")

    pdb_id = case["pdb_id"]
    entity_id = case["entity_id"]
    target_entity_num = entity_id.split("_", 1)[1] if "_" in entity_id else entity_id
    ligand_meta = case["ligand"]
    comp_id = ligand_meta["component_id"]

    cif_rel = case.get("structure_path", f"structures/{pdb_id.lower()}.cif.gz")
    cif_gz = manifest_path.parent / cif_rel
    if not cif_gz.exists():
        cif_gz = structure_cache / f"{pdb_id.lower()}.cif.gz"
    if not cif_gz.exists():
        raise FileNotFoundError(f"Source structure archive not found: {cif_gz}")

    cif_gz_sha256 = _sha256(cif_gz)
    expected_cif_gz_sha = case.get("structure_gzip_sha256")
    if expected_cif_gz_sha and cif_gz_sha256 != expected_cif_gz_sha:
        raise ValueError(f"Structure archive SHA-256 mismatch for {pdb_id}")

    git_rev = "unknown"
    git_bin = shutil.which("git")
    if git_bin:
        proc_git = subprocess.run(  # noqa: S603
            [git_bin, "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc_git.returncode == 0:
            git_rev = proc_git.stdout.strip()

    engine_dir = engine_python.parent
    vina_version = subprocess.run(  # noqa: S603
        [str(vina_path), "--version"], capture_output=True, text=True, check=True
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
    ).stdout.strip()

    ideal_sdf_path = ensure_ccd_ideal_sdf(comp_id, structure_cache)
    ideal_sdf_sha256 = _sha256(ideal_sdf_path)

    with tempfile.NamedTemporaryFile(suffix=".cif", delete=False) as tmp:
        with gzip.open(cif_gz, "rb") as gz:
            tmp.write(gz.read())
        tmp_cif = Path(tmp.name)

    try:
        cif_data = MMCIF2Dict(str(tmp_cif))
        native_mol = native_ligand_from_mmcif(
            tmp_cif,
            ideal_sdf_path,
            component_id=comp_id,
            auth_chain=ligand_meta["author_chain_id"],
            auth_seq_id=ligand_meta["author_residue_sequence"],
            label_asym_id=ligand_meta.get("label_asym_id"),
        )
    finally:
        tmp_cif.unlink(missing_ok=True)

    native_sdf_path = output_dir / f"{comp_id}_native.sdf"
    with Chem.SDWriter(str(native_sdf_path)) as writer:
        writer.write(native_mol)
    native_sdf_sha256 = _sha256(native_sdf_path)

    center, size = calculate_site(native_mol)
    half = [axis / 2.0 for axis in size]

    all_atom_rows = _atom_rows(cif_data)
    target_all = [
        a
        for a in all_atom_rows
        if a["pdbx_PDB_model_num"] in {"1", ""} and a["label_entity_id"] == target_entity_num
    ]
    target_atoms, target_issues, _ = _choose_protein_atoms(target_all)
    if target_issues:
        raise ValueError(f"Protein atom selection issues for {case_id}: {target_issues}")

    residue_atoms: dict[
        tuple[str, str, str, str], list[tuple[str, tuple[float, float, float]]]
    ] = {}
    source_lines: list[str] = []
    for idx, a in enumerate(target_atoms, 1):
        chain = a["auth_asym_id"][:1] if a["auth_asym_id"] else "A"
        resseq = int(a["auth_seq_id"])
        icode = a["pdbx_PDB_ins_code"][:1] if a["pdbx_PDB_ins_code"] else " "
        resname = a["label_comp_id"][:3]
        name = a["label_atom_id"]
        name = f" {name:<3s}" if len(name) < 4 else f"{name:<4s}"
        altloc = " "
        x = float(a["Cartn_x"])
        y = float(a["Cartn_y"])
        z = float(a["Cartn_z"])
        occ = 1.00
        element = a["type_symbol"][:2].strip().upper()
        atom_rec = (
            f"ATOM  {idx:5d} {name}{altloc}{resname:>3s} {chain}{resseq:4d}{icode}   "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{occ:6.2f}{0.00:6.2f}          {element:>2s}"
        )
        source_lines.append(atom_rec)
        key = (chain, str(resseq), icode.strip(), resname)
        residue_atoms.setdefault(key, []).append((atom_rec, (x, y, z)))

    selected_residues = select_residues(residue_atoms, center, half, 8.0)
    cropped_lines = [
        line
        for line in source_lines
        if (line[21:22], line[22:26].strip(), line[26:27].strip(), line[17:20].strip())
        in selected_residues
    ]
    receptor_crop = output_dir / "receptor_crop.pdb"
    receptor_crop.write_text("\n".join([*cropped_lines, "TER", "END"]) + "\n", encoding="ascii")
    receptor_crop_sha256 = _sha256(receptor_crop)

    receptor_pdbqt = output_dir / "receptor.pdbqt"
    receptor_json = output_dir / "receptor.json"
    rec_call = run_command(
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
        cwd=output_dir,
        stem="meeko_receptor",
    )
    if rec_call["returncode"] != 0:
        raise RuntimeError(f"Meeko receptor preparation failed: {rec_call}")

    ligand_pdbqt = output_dir / "ligand.pdbqt"
    lig_call = run_command(
        [
            str(engine_python),
            str(engine_dir / "mk_prepare_ligand.py"),
            "--mol",
            str(native_sdf_path),
            "--out",
            str(ligand_pdbqt),
            "--charge_model",
            "gasteiger",
            "--add_index_map",
        ],
        cwd=output_dir,
        stem="meeko_ligand",
    )
    if lig_call["returncode"] != 0:
        raise RuntimeError(f"Meeko ligand preparation failed: {lig_call}")

    poses_pdbqt = output_dir / "poses.pdbqt"
    vina_cmd = [
        "/usr/bin/time",
        "-v",
        str(vina_path),
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
        str(exhaustiveness),
        "--num_modes",
        str(num_modes),
        "--energy_range",
        str(energy_range),
        "--cpu",
        str(cpu_cores),
        "--seed",
        str(seed),
        "--out",
        str(poses_pdbqt),
    ]

    started = time.monotonic()
    vina_proc = subprocess.run(  # noqa: S603
        vina_cmd,
        cwd=output_dir,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    vina_runtime_sec = round(time.monotonic() - started, 3)
    (output_dir / "vina.stdout.log").write_text(vina_proc.stdout, encoding="utf-8")
    (output_dir / "vina.raw_stderr.log").write_text(vina_proc.stderr, encoding="utf-8")
    time_parse = parse_time_output(vina_proc.stderr)
    (output_dir / "vina.time.log").write_text(time_parse["time_summary"], encoding="utf-8")
    (output_dir / "vina.stderr.log").write_text(time_parse["clean_stderr"], encoding="utf-8")

    if vina_proc.returncode != 0:
        raise RuntimeError(f"Vina docking failed with returncode {vina_proc.returncode}")

    poses_sdf = output_dir / "poses.sdf"
    export_call = run_command(
        [
            str(engine_python),
            str(engine_dir / "mk_export.py"),
            "--write_sdf",
            str(poses_sdf),
            str(poses_pdbqt),
        ],
        cwd=output_dir,
        stem="meeko_export",
    )
    if export_call["returncode"] != 0:
        raise RuntimeError(f"Meeko export failed: {export_call}")

    pose_mols = [m for m in Chem.SDMolSupplier(str(poses_sdf), removeHs=False) if m is not None]
    native_heavy = Chem.RemoveHs(native_mol)
    pose_metrics: list[dict[str, Any]] = []

    vina_stdout = vina_proc.stdout
    score_pattern = re.compile(r"^\s*(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", re.MULTILINE)
    parsed_modes = score_pattern.findall(vina_stdout)
    score_by_mode = {int(m[0]): float(m[1]) for m in parsed_modes}

    for rank, docked_mol in enumerate(pose_mols, start=1):
        docked_heavy = Chem.RemoveHs(docked_mol)
        if docked_heavy.GetNumHeavyAtoms() != native_heavy.GetNumHeavyAtoms():
            raise ValueError(
                f"Docked pose {rank} heavy atom count {docked_heavy.GetNumHeavyAtoms()} "
                f"differs from native {native_heavy.GetNumHeavyAtoms()}"
            )
        rmsd = rdMolAlign.CalcRMS(docked_heavy, native_heavy, maxMatches=100000)
        score_kcal = score_by_mode.get(rank)
        pose_metrics.append(
            {
                "mode_rank": rank,
                "affinity_score_kcal_mol": score_kcal,
                "symmetry_corrected_no_fit_rmsd_A": round(rmsd, 4),
                "heavy_atom_count": docked_heavy.GetNumHeavyAtoms(),
            }
        )

    top1_rmsd = pose_metrics[0]["symmetry_corrected_no_fit_rmsd_A"]
    top1_success = bool(top1_rmsd < 2.0)
    top5_success = any(p["symmetry_corrected_no_fit_rmsd_A"] < 2.0 for p in pose_metrics[:5])
    best_rmsd = min(p["symmetry_corrected_no_fit_rmsd_A"] for p in pose_metrics)

    result_payload: dict[str, Any] = {
        "schema": "caddsuite.redocking-preregistered-attempt/1",
        "case_id": case_id,
        "pdb_id": pdb_id,
        "entity_id": entity_id,
        "seed": seed,
        "cluster_id": case.get("cluster_id"),
        "status": "completed",
        "primary_endpoint": {
            "top1_symmetry_corrected_no_fit_rmsd_A": top1_rmsd,
            "top1_success_threshold_2_0A": top1_success,
            "verdict": "success" if top1_success else "failure",
        },
        "secondary_endpoints": {
            "top5_success": top5_success,
            "best_sampled_rmsd_A": best_rmsd,
            "returned_mode_count": len(pose_metrics),
        },
        "resource_consumption": {
            "sidecar": "/usr/bin/time -v",
            "vina_wall_clock_seconds": time_parse["metrics"].get(
                "wall_time_seconds", vina_runtime_sec
            ),
            "vina_runtime_seconds_monotonic": vina_runtime_sec,
            "user_time_seconds": time_parse["metrics"].get("user_time_seconds"),
            "system_time_seconds": time_parse["metrics"].get("system_time_seconds"),
            "cpu_percent": time_parse["metrics"].get("cpu_percent"),
            "peak_rss_kbytes": time_parse["metrics"].get("peak_rss_kbytes"),
            "peak_rss_mib": time_parse["metrics"].get("peak_rss_mib"),
            "voluntary_context_switches": time_parse["metrics"].get("voluntary_context_switches"),
            "involuntary_context_switches": time_parse["metrics"].get(
                "involuntary_context_switches"
            ),
        },
        "protocol": {
            "scoring_function": "vina",
            "exhaustiveness": exhaustiveness,
            "num_modes": num_modes,
            "energy_range_kcal_mol": energy_range,
            "cpu_cores": cpu_cores,
            "seed": seed,
            "site_center_A": center,
            "site_size_A": size,
            "crop_rule": "retain complete residues having any atom within box expanded by 8.0 A",
            "crop_statistics": {
                "total_target_residues": len(residue_atoms),
                "retained_residues": len(selected_residues),
                "cropped_atom_lines": len(cropped_lines),
            },
        },
        "poses": pose_metrics,
        "provenance": {
            "git_commit": git_rev,
            "vina_version": vina_version,
            "vina_executable": str(vina_path),
            "vina_executable_sha256": _sha256(vina_path),
            "meeko_version": meeko_version,
            "engine_python": str(engine_python),
            "cif_gz_sha256": cif_gz_sha256,
            "ideal_sdf_sha256": ideal_sdf_sha256,
            "native_sdf_sha256": native_sdf_sha256,
            "receptor_crop_sha256": receptor_crop_sha256,
            "receptor_pdbqt_sha256": _sha256(receptor_pdbqt),
            "ligand_pdbqt_sha256": _sha256(ligand_pdbqt),
            "poses_pdbqt_sha256": _sha256(poses_pdbqt),
            "poses_sdf_sha256": _sha256(poses_sdf),
        },
    }

    result_json = output_dir / "attempt_result.json"
    result_json.write_text(
        json.dumps(result_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest_lines = []
    for f in sorted(output_dir.iterdir()):
        if f.is_file() and f.name != "SHA256SUMS":
            manifest_lines.append(f"{_sha256(f)}  {f.name}\n")
    (output_dir / "SHA256SUMS").write_text("".join(manifest_lines), encoding="ascii")

    return result_payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "benchmarks/redocking/pilot_v3/cohort-30-20260929/cohort_manifest.json",
    )
    parser.add_argument("--case-id", default="REDOCK-001")
    parser.add_argument("--seed", type=int, default=42)
    default_out = (
        ROOT / "benchmarks/redocking/pilot_v3/runs/preregistered-cohort-v3/REDOCK-001/seed_42"
    )
    parser.add_argument("--output-dir", type=Path, default=default_out)
    parser.add_argument(
        "--vina",
        type=Path,
        default=Path("/home/sridhar/miniconda3/envs/cadd/bin/vina"),
    )
    parser.add_argument(
        "--engine-python",
        type=Path,
        default=Path("/home/sridhar/miniconda3/envs/cadd/bin/python"),
    )
    parser.add_argument(
        "--structure-cache",
        type=Path,
        default=ROOT / "benchmarks/redocking/pilot_v3/cohort-30-20260929/structures",
    )
    parser.add_argument("--exhaustiveness", type=int, default=16)
    parser.add_argument("--num-modes", type=int, default=9)
    parser.add_argument("--energy-range", type=float, default=3.0)
    parser.add_argument("--cpu-cores", type=int, default=2)
    args = parser.parse_args()

    result = run_attempt(
        args.manifest.resolve(strict=True),
        args.case_id,
        args.seed,
        args.output_dir.resolve(),
        vina_path=args.vina.resolve(strict=True),
        engine_python=args.engine_python.resolve(strict=True),
        structure_cache=args.structure_cache.resolve(strict=True),
        exhaustiveness=args.exhaustiveness,
        num_modes=args.num_modes,
        energy_range=args.energy_range,
        cpu_cores=args.cpu_cores,
    )

    t1_rmsd = result["primary_endpoint"]["top1_symmetry_corrected_no_fit_rmsd_A"]
    res = result["resource_consumption"]
    print("\n" + "=" * 60)
    print(f"BENCHMARK ATTEMPT RESULT: {result['case_id']} (Seed {result['seed']})")
    print("=" * 60)
    print(f"PDB: {result['pdb_id']} | Entity: {result['entity_id']}")
    print(f"Primary Top-1 RMSD: {t1_rmsd:.4f} Å")
    print(f"Primary Verdict: {result['primary_endpoint']['verdict'].upper()}")
    print(f"Top-5 Success: {result['secondary_endpoints']['top5_success']}")
    print(f"Best Sampled RMSD: {result['secondary_endpoints']['best_sampled_rmsd_A']:.4f} Å")
    print(f"Peak RSS: {res['peak_rss_mib']} MiB ({res['peak_rss_kbytes']} KB)")
    print(f"Wall Clock Time: {res['vina_wall_clock_seconds']} s")
    print(f"CPU Utilization: {res['cpu_percent']}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
