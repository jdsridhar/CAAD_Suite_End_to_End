"""Read real trajectory dimensions and atom selections in an isolated MDA environment."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import sys
from itertools import pairwise
from pathlib import Path


def inspect(request: dict[str, object], root: Path) -> dict[str, object]:
    mda = importlib.import_module("MDAnalysis")

    paths: dict[str, Path] = {}
    hashes = request["hashes"]
    if not isinstance(hashes, dict):
        raise ValueError("inspection hashes must be explicit")
    for role in ("topology", "trajectory"):
        path = (root / str(request[role])).resolve(strict=True)
        if not path.is_relative_to(root.resolve()):
            raise ValueError("inspection input escaped its private directory")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != hashes.get(role):
            raise ValueError(f"{role} hash verification failed")
        paths[role] = path
    universe = mda.Universe(str(paths["topology"]), str(paths["trajectory"]))
    if len(universe.trajectory) < 2:
        raise ValueError("at least two trajectory frames are required")
    times = [float(frame.time) for frame in universe.trajectory]
    dt = times[1] - times[0]
    if not all(math.isfinite(t) for t in times) or dt <= 0 or times[0] < 0:
        raise ValueError("trajectory times must be finite and increasing")
    if any(not math.isclose(b - a, dt, rel_tol=1e-4, abs_tol=1e-5) for a, b in pairwise(times)):
        raise ValueError("nonuniform frame sampling requires a separate explicit processing plan")
    expressions = request["selections"]
    if not isinstance(expressions, dict):
        raise ValueError("explicit selections are required")
    selections = {}
    selected_indices: dict[str, set[int]] = {}
    for name, expression in expressions.items():
        if re.search(
            r"\b(around|sphzone|sphlayer|cyzone|cylayer|point|prop|isolayer)\b", str(expression)
        ):
            raise ValueError(
                "Guided analysis requires static atom selections, not spatial selections"
            )
        atoms = universe.select_atoms(str(expression))
        minimum = 3 if name in {"backbone", "protein_ca"} else 1
        if len(atoms) < minimum:
            raise ValueError(f"selection {name!r} contains fewer than {minimum} atoms")
        selections[str(name)] = {"description": str(expression), "n_atoms": len(atoms)}
        selected_indices[str(name)] = {int(index) + 1 for index in atoms.indices}
    if {"protein", "ligand"}.issubset(selected_indices) and (
        selected_indices["protein"] & selected_indices["ligand"]
    ):
        raise ValueError("Protein and ligand selections must not overlap")
    if {"surface", "sasa_output"}.issubset(selected_indices) and not (
        selected_indices["sasa_output"].issubset(selected_indices["surface"])
    ):
        raise ValueError("SASA output selection must be a subset of its surface selection")
    result = {
        "protocol": "caddsuite.trajectory-inspection/1",
        "mdanalysis_version": mda.__version__,
        "hashes": hashes,
        "n_atoms": len(universe.atoms),
        "n_frames": len(times),
        "frame_interval_ps": dt,
        "start_time_ps": times[0],
        "end_time_ps": times[-1],
        "selections": selections,
    }
    groups = request.get("index_groups")
    if groups is not None:
        if not isinstance(groups, dict) or not groups:
            raise ValueError("Index groups must be an explicit nonempty mapping")
        lines = ["[ System ]"]
        all_groups = {"System": set(range(1, len(universe.atoms) + 1))}
        for key, group_name in groups.items():
            if key not in selected_indices or not re.fullmatch(r"CSA_[A-Za-z]+", str(group_name)):
                raise ValueError("Index group names or selected atoms are invalid")
            if group_name in all_groups:
                raise ValueError("Index group names must be unique")
            all_groups[str(group_name)] = selected_indices[key]
        lines = []
        for name, indices in all_groups.items():
            lines.append(f"[ {name} ]")
            values = sorted(indices)
            lines.extend(" ".join(map(str, values[i : i + 15])) for i in range(0, len(values), 15))
        index_path = root / "analysis-groups.ndx"
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result["index"] = {
            "path": index_path.name,
            "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "groups": groups,
        }
    return result


def main() -> int:
    path = Path(sys.argv[1]).resolve(strict=True)
    try:
        result = inspect(json.loads(path.read_text()), path.parent)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
