"""Read real trajectory dimensions and atom selections in an isolated MDA environment."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
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
    for name, expression in expressions.items():
        atoms = universe.select_atoms(str(expression))
        if len(atoms) < 3:
            raise ValueError(f"selection {name!r} contains fewer than three atoms")
        selections[str(name)] = {"description": str(expression), "n_atoms": len(atoms)}
    return {
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
