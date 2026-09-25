"""Isolated MDAnalysis worker for explicitly selected coordinate metrics.

This file intentionally imports no caddsuite package. Run it with the pinned optional analysis
environment against private staged copies of the trajectory and topology.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any


class WorkerFailure(ValueError):
    """A staged analysis request or coordinate metric is invalid."""


_SUPPORTED_METRICS = {
    "backbone_rmsd",
    "ligand_pose_rmsd",
    "ligand_internal_rmsd",
    "protein_ca_rmsf",
    "protein_radius_of_gyration",
    "protein_ligand_min_distance",
    "protein_ligand_contact_count",
}
_METRIC_NAMES = {
    "backbone_rmsd": ("rmsd_backbone", "Å"),
    "ligand_pose_rmsd": ("rmsd_ligand_pose", "Å"),
    "ligand_internal_rmsd": ("rmsd_ligand_internal", "Å"),
    "protein_ca_rmsf": ("rmsf_ca", "Å"),
    "protein_radius_of_gyration": ("rg_protein", "Å"),
    "protein_ligand_min_distance": ("mindist_protein_ligand", "Å"),
    "protein_ligand_contact_count": ("contacts_protein_ligand", "atom_pairs"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _confined_input(root: Path, value: object, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkerFailure(f"{role} path is missing")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise WorkerFailure(f"{role} path is not a confined canonical relative path")
    path = root.joinpath(*relative.parts).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise WorkerFailure(f"{role} is outside the private stage or is not a file")
    return path


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkerFailure(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise WorkerFailure(f"{label} must be finite")
    return result


def _selection(universe: Any, request: dict[str, Any], key: str) -> Any:
    selections = request.get("selections")
    if not isinstance(selections, dict) or key not in selections:
        raise WorkerFailure(f"required atom selection {key!r} is absent")
    spec = selections[key]
    if not isinstance(spec, dict):
        raise WorkerFailure(f"atom selection {key!r} is malformed")
    expression = spec.get("description")
    expected_count = spec.get("expected_atom_count")
    if not isinstance(expression, str) or not expression:
        raise WorkerFailure(f"atom selection {key!r} has no selection expression")
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count < 1
    ):
        raise WorkerFailure(f"atom selection {key!r} has an invalid expected atom count")
    try:
        atoms = universe.select_atoms(expression)
    except Exception as exc:
        raise WorkerFailure(f"MDAnalysis could not parse selection {key!r}: {exc}") from exc
    if len(atoms) != expected_count:
        raise WorkerFailure(
            f"selection {key!r} resolved to {len(atoms)} atoms; expected {expected_count}"
        )
    return atoms


def _kabsch_rmsd(numpy: Any, mobile: Any, reference: Any, weights: Any | None = None) -> float:
    aligned = _kabsch_align(numpy, mobile, reference, weights)
    delta = aligned - reference
    squared = numpy.einsum("ij,ij->i", delta, delta)
    if weights is None:
        return float(numpy.sqrt(numpy.mean(squared)))
    return float(numpy.sqrt(numpy.average(squared, weights=weights)))


def _kabsch_align(numpy: Any, mobile: Any, reference: Any, weights: Any | None = None) -> Any:
    if mobile.shape != reference.shape or mobile.ndim != 2 or mobile.shape[1] != 3:
        raise WorkerFailure("RMSD coordinate arrays have incompatible shapes")
    if mobile.shape[0] < 3:
        raise WorkerFailure("RMSD fitting requires at least three selected atoms")
    if weights is None:
        mobile_center = mobile.mean(axis=0)
        reference_center = reference.mean(axis=0)
        weighted_reference = None
    else:
        weight_array = numpy.asarray(weights, dtype=float)
        if (
            weight_array.shape != (mobile.shape[0],)
            or not numpy.isfinite(weight_array).all()
            or numpy.any(weight_array <= 0)
        ):
            raise WorkerFailure("RMSD weights are malformed, non-finite, or non-positive")
        mobile_center = numpy.average(mobile, axis=0, weights=weight_array)
        reference_center = numpy.average(reference, axis=0, weights=weight_array)
        weighted_reference = weight_array[:, numpy.newaxis]
    centered_mobile = mobile - mobile_center
    centered_reference = reference - reference_center
    if numpy.linalg.matrix_rank(centered_reference, tol=1e-6) < 2:
        raise WorkerFailure("RMSD reference selection is collinear or geometrically degenerate")
    covariance = centered_mobile.T @ (
        centered_reference
        if weighted_reference is None
        else centered_reference * weighted_reference
    )
    left, _singular, right = numpy.linalg.svd(covariance)
    correction = numpy.eye(3)
    correction[2, 2] = numpy.linalg.det(left @ right)
    rotation = left @ correction @ right
    return centered_mobile @ rotation + reference_center


def _direct_rmsd(numpy: Any, mobile: Any, reference: Any, weights: Any | None = None) -> float:
    if mobile.shape != reference.shape:
        raise WorkerFailure("RMSD atom ordering differs from the reference frame")
    delta = mobile - reference
    squared = numpy.einsum("ij,ij->i", delta, delta)
    if weights is None:
        return float(numpy.sqrt(numpy.mean(squared)))
    return float(numpy.sqrt(numpy.average(squared, weights=weights)))


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _summary(numpy: Any, values: list[float]) -> dict[str, float]:
    array = numpy.asarray(values, dtype=float)
    if len(array) == 0 or not numpy.isfinite(array).all():
        raise WorkerFailure("metric produced no values or a non-finite value")
    return {
        "n": float(len(array)),
        "mean": float(numpy.mean(array)),
        "sd_population": float(numpy.std(array, ddof=0)),
        "min": float(numpy.min(array)),
        "max": float(numpy.max(array)),
    }


def _run(
    request: dict[str, Any],
    request_path: Path,
    output: Path,
    root: Path,
    argv: list[str],
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    mda = import_module("MDAnalysis")
    numpy = import_module("numpy")
    distances = import_module("MDAnalysis.lib.distances")
    trajectory_spec = request.get("trajectory")
    topology_spec = request.get("topology")
    reference_spec = request.get("reference_structure")
    mass_spec = request.get("atom_masses")
    if (
        not isinstance(trajectory_spec, dict)
        or not isinstance(topology_spec, dict)
        or (reference_spec is not None and not isinstance(reference_spec, dict))
        or (mass_spec is not None and not isinstance(mass_spec, dict))
    ):
        raise WorkerFailure("trajectory/topology/reference artifact records are malformed")
    trajectory = _confined_input(root, trajectory_spec.get("path"), "trajectory")
    topology = _confined_input(root, topology_spec.get("path"), "topology")
    reference_path = (
        _confined_input(root, reference_spec.get("path"), "reference structure")
        if isinstance(reference_spec, dict)
        else None
    )
    trajectory_hash = _sha256(trajectory)
    topology_hash = _sha256(topology)
    if trajectory_hash != trajectory_spec.get("sha256"):
        raise WorkerFailure("staged trajectory hash differs from its manifest")
    if topology_hash != topology_spec.get("sha256"):
        raise WorkerFailure("staged topology hash differs from its manifest")
    reference_hash = _sha256(reference_path) if reference_path is not None else None
    if reference_hash != (
        reference_spec.get("sha256") if isinstance(reference_spec, dict) else None
    ):
        raise WorkerFailure("staged reference structure hash differs from its manifest")
    mass_path = (
        _confined_input(root, mass_spec.get("path"), "atom-mass table")
        if isinstance(mass_spec, dict)
        else None
    )
    mass_hash = _sha256(mass_path) if mass_path is not None else None
    if mass_hash != (mass_spec.get("sha256") if isinstance(mass_spec, dict) else None):
        raise WorkerFailure("staged atom-mass table hash differs from its manifest")
    if request.get("protocol") != "caddsuite.mdanalysis-metrics/1":
        raise WorkerFailure("unsupported worker protocol")
    if request.get("trajectory_format") != "XTC" or request.get("topology_format") != "GRO":
        raise WorkerFailure("this worker requires a GRO topology and XTC trajectory")

    expected_atoms = request.get("expected_atom_count")
    expected_frames = request.get("expected_frame_count")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (expected_atoms, expected_frames)
    ):
        raise WorkerFailure("expected atom/frame counts must be positive integers")
    universe = mda.Universe(str(topology), str(trajectory))
    if len(universe.atoms) != expected_atoms or len(universe.trajectory) != expected_frames:
        raise WorkerFailure("GRO/XTC atom or frame count differs from the hash-linked request")
    metric_values = request.get("metrics")
    rmsd_weighting = request.get("rmsd_weighting", "uniform")
    if rmsd_weighting not in {"uniform", "mass"}:
        raise WorkerFailure("rmsd_weighting must be uniform or mass")
    needs_masses = isinstance(metric_values, list) and (
        "protein_radius_of_gyration" in metric_values
        or (
            rmsd_weighting == "mass"
            and bool(
                {"backbone_rmsd", "ligand_pose_rmsd", "ligand_internal_rmsd"}.intersection(
                    metric_values
                )
            )
        )
    )
    if needs_masses and mass_path is None:
        raise WorkerFailure("protein radius of gyration requires an exact atom-mass table")
    if mass_path is not None:
        try:
            mass_payload = json.loads(mass_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkerFailure(f"atom-mass table is not valid JSON: {exc}") from exc
        if (
            not isinstance(mass_payload, dict)
            or mass_payload.get("protocol") != "caddsuite.atom-masses/1"
            or mass_payload.get("n_atoms") != expected_atoms
            or mass_payload.get("mass_unit") != "Da"
            or not isinstance(mass_payload.get("masses_Da"), list)
            or len(mass_payload["masses_Da"]) != expected_atoms
        ):
            raise WorkerFailure("atom-mass table protocol or atom count is invalid")
        masses = numpy.asarray(mass_payload["masses_Da"], dtype=float)
        if not numpy.isfinite(masses).all() or numpy.any(masses <= 0):
            raise WorkerFailure("atom-mass table contains non-positive or non-finite values")
        universe.atoms.masses = masses
    reference_universe = (
        mda.Universe(str(reference_path)) if reference_path is not None else universe
    )
    if len(reference_universe.atoms) != expected_atoms:
        raise WorkerFailure("reference structure atom count differs from the system")
    frame_interval = _finite(request.get("frame_interval_ps"), "frame_interval_ps")
    times_ps: list[float] = []
    for ts in universe.trajectory:
        times_ps.append(float(ts.time))
    if len(times_ps) < 2 or any(not math.isfinite(t) for t in times_ps):
        raise WorkerFailure("trajectory requires at least two frames with finite times")
    intervals = numpy.diff(numpy.asarray(times_ps))
    if numpy.any(intervals <= 0) or not numpy.allclose(
        intervals, frame_interval, rtol=0.0, atol=1e-4
    ):
        raise WorkerFailure("trajectory frame times are non-increasing or non-uniform")
    start_ns = _finite(request.get("start_time_ns"), "start_time_ns")
    end_ns = _finite(request.get("end_time_ns"), "end_time_ns")
    stride = request.get("stride")
    if isinstance(stride, bool) or not isinstance(stride, int) or stride < 1:
        raise WorkerFailure("stride must be a positive integer")
    selected_indices = [
        index
        for index, time_ps in enumerate(times_ps)
        if start_ns * 1000 <= time_ps <= end_ns * 1000
    ][::stride]
    if len(selected_indices) < 2:
        raise WorkerFailure("analysis window and stride select fewer than two frames")
    ref_frame = request.get("reference_frame")
    if (
        isinstance(ref_frame, bool)
        or not isinstance(ref_frame, int)
        or not 0 <= ref_frame < len(times_ps)
    ):
        raise WorkerFailure("reference_frame is outside the trajectory")

    if (
        not isinstance(metric_values, list)
        or not metric_values
        or set(metric_values).difference(_SUPPORTED_METRICS)
    ):
        raise WorkerFailure("requested metric list is empty or contains unsupported metrics")
    if len(set(metric_values)) != len(metric_values):
        raise WorkerFailure("requested metrics contain duplicates")
    contact_cutoff = _finite(request.get("contact_cutoff_A"), "contact_cutoff_A")
    if contact_cutoff <= 0:
        raise WorkerFailure("contact cutoff must be positive")
    distance_mode = request.get("distance_mode")
    if distance_mode not in {"minimum_image", "cartesian_unwrapped"}:
        raise WorkerFailure("distance mode must be minimum_image or cartesian_unwrapped")

    requested_selections = request.get("selections")
    if not isinstance(requested_selections, dict):
        raise WorkerFailure("selection map is malformed")
    selection_receipts: dict[str, dict[str, object]] = {}
    groups: dict[str, Any] = {}
    keys: set[str] = set()
    metric_selections = {
        "backbone_rmsd": {"backbone"},
        "ligand_pose_rmsd": {"ligand"},
        "ligand_internal_rmsd": {"ligand"},
        "protein_ca_rmsf": {"protein_ca"},
        "protein_radius_of_gyration": {"protein"},
        "protein_ligand_min_distance": {"protein", "ligand"},
        "protein_ligand_contact_count": {"protein", "ligand"},
    }
    for metric in metric_values:
        keys.update(metric_selections[metric])
    for key in sorted(keys):
        groups[key] = _selection(universe, request, key)
        selection_receipts[key] = {
            "description": requested_selections[key]["description"],
            "n_atoms": len(groups[key]),
        }
    pose_fit = request.get("pose_fit_selection")
    pose_fit_group = None
    if "ligand_pose_rmsd" in metric_values:
        if not isinstance(pose_fit, dict):
            raise WorkerFailure("pose RMSD requires its upstream alignment selection receipt")
        try:
            pose_fit_group = universe.select_atoms(pose_fit["description"])
        except Exception as exc:
            raise WorkerFailure(f"could not resolve pose fit selection: {exc}") from exc
        if len(pose_fit_group) != pose_fit.get("expected_atom_count") or len(pose_fit_group) < 3:
            raise WorkerFailure("pose fit selection count is mismatched or fewer than three atoms")
        selection_receipts["pose_fit"] = {
            "description": pose_fit["description"],
            "n_atoms": len(pose_fit_group),
        }
    for key in ("backbone", "ligand"):
        if key in groups and len(groups[key]) < 3:
            raise WorkerFailure(f"selection {key!r} is too small for fitted RMSD")

    reference = ref_frame
    reference_positions: dict[str, Any] = {}
    for key in {"backbone", "ligand", "protein_ca"}.intersection(groups):
        reference_group = _selection(reference_universe, request, key)
        if reference_universe is universe:
            universe.trajectory[reference]
        reference_positions[key] = reference_group.positions.astype(float, copy=True)
    if reference_universe is universe:
        universe.trajectory[reference]
    if "pose_fit" in selection_receipts:
        if reference_universe is universe:
            universe.trajectory[reference]
        if not isinstance(pose_fit, dict):
            raise WorkerFailure("pose fit selection details are missing")
        reference_fit_group = reference_universe.select_atoms(pose_fit["description"])
        if len(reference_fit_group) != pose_fit.get("expected_atom_count"):
            raise WorkerFailure("reference pose-fit selection atom count differs")
        reference_pose_fit = reference_fit_group.positions.astype(float, copy=True)
        if (
            numpy.linalg.matrix_rank(reference_pose_fit - reference_pose_fit.mean(axis=0), tol=1e-6)
            < 2
        ):
            raise WorkerFailure("pose fit reference selection is collinear or degenerate")

    frame_records: list[tuple[int, float]] = []
    for index in selected_indices:
        ts = universe.trajectory[index]
        frame_records.append((index, float(ts.time) / 1000.0))
    values: dict[str, list[float]] = {metric: [] for metric in metric_values}
    residue_rows: list[tuple[int, str, str, list[Any]]] = []
    for index, _time_ns in frame_records:
        ts = universe.trajectory[index]
        if "backbone_rmsd" in metric_values:
            values["backbone_rmsd"].append(
                _kabsch_rmsd(
                    numpy,
                    groups["backbone"].positions,
                    reference_positions["backbone"],
                    groups["backbone"].masses if rmsd_weighting == "mass" else None,
                )
            )
        if "ligand_pose_rmsd" in metric_values:
            values["ligand_pose_rmsd"].append(
                _direct_rmsd(
                    numpy,
                    groups["ligand"].positions,
                    reference_positions["ligand"],
                    groups["ligand"].masses if rmsd_weighting == "mass" else None,
                )
            )
        if "ligand_internal_rmsd" in metric_values:
            values["ligand_internal_rmsd"].append(
                _kabsch_rmsd(
                    numpy,
                    groups["ligand"].positions,
                    reference_positions["ligand"],
                    groups["ligand"].masses if rmsd_weighting == "mass" else None,
                )
            )
        if "protein_radius_of_gyration" in metric_values:
            rg = float(groups["protein"].radius_of_gyration())
            if not math.isfinite(rg):
                raise WorkerFailure("protein radius of gyration is non-finite")
            values["protein_radius_of_gyration"].append(rg)
        if {"protein_ligand_min_distance", "protein_ligand_contact_count"}.intersection(
            metric_values
        ):
            distances_matrix = distances.distance_array(
                groups["protein"].positions,
                groups["ligand"].positions,
                box=ts.dimensions if distance_mode == "minimum_image" else None,
            )
            if "protein_ligand_min_distance" in metric_values:
                values["protein_ligand_min_distance"].append(float(numpy.min(distances_matrix)))
            if "protein_ligand_contact_count" in metric_values:
                values["protein_ligand_contact_count"].append(
                    float(numpy.count_nonzero(distances_matrix < contact_cutoff))
                )

    if "protein_ca_rmsf" in metric_values:
        positions: list[Any] = []
        reference_ca = reference_positions["protein_ca"]
        for index in selected_indices:
            universe.trajectory[index]
            positions.append(
                _kabsch_align(
                    numpy,
                    groups["protein_ca"].positions.astype(float, copy=True),
                    reference_ca,
                    groups["protein_ca"].masses if rmsd_weighting == "mass" else None,
                )
            )
        coords = numpy.stack(positions, axis=0)
        centered = coords - coords.mean(axis=0, keepdims=True)
        rmsf = numpy.sqrt(numpy.mean(numpy.einsum("fai,fai->fa", centered, centered), axis=0))
        ca = groups["protein_ca"]
        residue_rows = [
            (int(atom.resid), str(atom.resname), str(atom.name), [float(value)])
            for atom, value in zip(ca, rmsf, strict=True)
        ]
        values["protein_ca_rmsf"] = [float(value) for value in rmsf]

    output.mkdir(parents=True, exist_ok=False)
    reported: list[dict[str, object]] = []
    for metric in metric_values:
        name, unit = _METRIC_NAMES[metric]
        path = output / f"{name}.csv"
        if metric == "protein_ca_rmsf":
            rows = [
                [resid, rmsf[0], resname, atomname]
                for resid, resname, atomname, rmsf in residue_rows
            ]
            _write_csv(path, ["residue", "value", "resname", "atom"], rows)
            summary_values = values[metric]
        else:
            rows = [
                [time_ns, value]
                for (_index, time_ns), value in zip(frame_records, values[metric], strict=True)
            ]
            header = ["time_ns", "value"]
            _write_csv(path, header, rows)
            summary_values = values[metric]
        reported.append(
            {
                "name": name,
                "metric": metric,
                "unit": unit,
                "file": path.name,
                "sha256": _sha256(path),
                "n_values": len(summary_values),
                "summary": _summary(numpy, summary_values),
            }
        )
    metadata = {
        "mdanalysis_version": mda.__version__,
        "numpy_version": numpy.__version__,
        "n_atoms": len(universe.atoms),
        "n_frames": len(universe.trajectory),
        "first_time_ps": times_ps[0],
        "last_time_ps": times_ps[-1],
        "frame_interval_ps": frame_interval,
        "n_frames_analyzed": len(selected_indices),
        "trajectory_sha256": trajectory_hash,
        "topology_sha256": topology_hash,
        "reference_structure_sha256": reference_hash,
        "atom_masses_sha256": mass_hash,
        "reference_coordinates": "explicit_structure"
        if reference_path is not None
        else "trajectory_frame",
        "trajectory_dimensions_A_deg": [
            float(value) for value in universe.trajectory[-1].dimensions
        ],
        "radius_of_gyration_mass_basis": (
            "GROMACS TPR atom mass table"
            if mass_path is not None
            else "unavailable: no explicit mass table supplied"
        ),
        "rmsd_weighting": rmsd_weighting,
        "protein_ligand_distance_mode": distance_mode,
    }
    result = {
        "protocol": "caddsuite.mdanalysis-metrics/1",
        "request_id": request.get("request_id"),
        "simulation_id": request.get("simulation_id"),
        "trajectory_id": request.get("trajectory_id"),
        "preprocessing_result_id": request.get("preprocessing_result_id"),
        "selection_receipts": selection_receipts,
        "time_window_ns": [start_ns, end_ns],
        "frame_indices": selected_indices,
        "metrics": reported,
        "metadata": metadata,
    }
    result_path = output / "result.json"
    result_path.write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    command_record = {
        "argv": argv,
        "request_sha256": _sha256(request_path),
        "started_at_utc": started_at,
        "ended_at_utc": datetime.now(UTC).isoformat(),
        "worker": "caddsuite_worker.mdanalysis_metrics_worker",
        "input_artifacts": {
            "trajectory": trajectory_hash,
            "topology": topology_hash,
            **({"atom_masses": mass_hash} if mass_hash is not None else {}),
        },
    }
    (output / "commands.json").write_text(
        json.dumps(command_record, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    args = parser.parse_args()
    del args.timeout_seconds  # The supervising executor enforces the process timeout.
    root = Path.cwd().resolve(strict=True)
    try:
        request_path = _confined_input(root, args.request, "worker request")
        output_path = PurePosixPath(args.output_dir)
        if (
            output_path.is_absolute()
            or output_path.as_posix() != args.output_dir
            or "\\" in args.output_dir
            or any(part in {"", ".", ".."} for part in output_path.parts)
        ):
            raise WorkerFailure("output directory must be a confined canonical relative path")
        output = root.joinpath(*output_path.parts)
        if (
            output.exists()
            or output.is_symlink()
            or not output.resolve(strict=False).is_relative_to(root)
        ):
            raise WorkerFailure("output directory exists or escapes the private stage")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise WorkerFailure("worker request must be a JSON object")
        _run(request, request_path, output, root, sys.argv)
    except Exception as exc:
        print(f"MDANALYSIS_METRICS.{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
