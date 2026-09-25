"""Safe read-only inventory planning for legacy Docking Suite and MDSuite projects."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

LegacyKind = Literal["docking", "md"]
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
_DOCKING_SUFFIXES = {
    ".csv",
    ".conf",
    ".log",
    ".pdb",
    ".pdbqt",
    ".sdf",
    ".mol2",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".png",
}
_MD_SUFFIXES = {
    ".conf",
    ".log",
    ".mdp",
    ".top",
    ".itp",
    ".ndx",
    ".gro",
    ".pdb",
    ".psf",
    ".mol2",
    ".crd",
    ".par",
    ".rtf",
    ".csv",
    ".dat",
    ".xvg",
    ".txt",
    ".md",
}
_CONFIG_KEYS = {
    "docking": {"EXHAUSTIVENESS", "NUM_MODES", "VINA_SEED", "BOX_PAD", "BOX_FLOOR", "NCORES", "PH"},
    "md": {"TARGET_NS", "NCORES", "OMP_THREADS", "GPU_DEVICE"},
}
_VERSION = re.compile(r"GROMACS[^\n]*?([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[A-Za-z0-9_.-]+)?)")


@dataclass(frozen=True, slots=True)
class LegacyFile:
    relative_path: str
    size_bytes: int
    sha256: str
    category: str


@dataclass(frozen=True, slots=True)
class OmittedFile:
    relative_path: str
    size_bytes: int
    reason: str


@dataclass(frozen=True, slots=True)
class LegacyImportPlan:
    kind: LegacyKind
    source_root: Path
    source_name: str
    manifest_sha256: str
    metadata: dict[str, object]
    files: tuple[LegacyFile, ...]
    omitted: tuple[OmittedFile, ...]
    completeness: Literal["partial"] = "partial"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source_root": str(self.source_root),
            "source_name": self.source_name,
            "manifest_sha256": self.manifest_sha256,
            "completeness": self.completeness,
            "metadata": self.metadata,
            "files": [asdict(item) for item in self.files],
            "omitted": [
                {
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "reason": item.reason,
                }
                for item in self.omitted
            ],
            "total_selected_bytes": sum(item.size_bytes for item in self.files),
        }


def plan_legacy_import(
    source_root: Path,
    *,
    kind: LegacyKind,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> LegacyImportPlan:
    """Validate project structure and hash an allowlisted, size-bounded file inventory.

    The function never executes project configuration, launches scientific software, or
    writes into the source project. Large trajectory binaries are inventoried as omitted.
    """
    root = source_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("legacy source must be a directory")
    if kind not in ("docking", "md"):
        raise ValueError(f"unsupported legacy project kind: {kind!r}")
    conf = root / "project.conf"
    if not conf.is_file() or conf.is_symlink():
        raise ValueError("legacy project.conf is missing or is not a regular file")
    if kind == "docking":
        if not ((root / "results.csv").is_file() or (root / "jobs.csv").is_file()):
            raise ValueError("docking project requires results.csv or jobs.csv")
    elif not (root / "gromacs").is_dir():
        raise ValueError("MD project requires a gromacs/ directory")

    metadata: dict[str, object] = {"configuration": _read_project_config(conf, kind)}
    if kind == "docking":
        for name in ("jobs.csv", "results.csv"):
            path = root / name
            if path.is_file():
                metadata[name] = _csv_summary(path)
    else:
        metadata["engine_versions"] = _gromacs_versions(root / "gromacs")
        metadata["mdp_observations"] = _mdp_observations(root / "gromacs")

    allowed = _DOCKING_SUFFIXES if kind == "docking" else _MD_SUFFIXES
    omitted: list[OmittedFile] = []
    selected: list[LegacyFile] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            omitted.append(OmittedFile(relative, 0, "symlink or path escapes project root"))
            continue
        if any(
            part.startswith(".") and part not in {".md_done"}
            for part in path.relative_to(root).parts
        ):
            omitted.append(
                OmittedFile(relative, path.stat().st_size, "hidden state or temporary file")
            )
            continue
        if path.name.endswith(":Zone.Identifier") or path.name.startswith("#"):
            omitted.append(
                OmittedFile(relative, path.stat().st_size, "filesystem metadata or editor backup")
            )
            continue
        if kind == "md" and path.suffix.lower() not in allowed:
            omitted.append(
                OmittedFile(relative, path.stat().st_size, "large or unsupported MD artifact type")
            )
            continue
        if kind == "docking" and path.suffix.lower() not in allowed:
            omitted.append(
                OmittedFile(relative, path.stat().st_size, "unsupported docking artifact type")
            )
            continue
        if (
            kind == "md"
            and path.suffix.lower() == ".gro"
            and path.name
            not in {
                "step3_input.gro",
                "step4.0_minimization.gro",
                "step4.1_equilibration.gro",
            }
        ):
            omitted.append(
                OmittedFile(
                    relative, path.stat().st_size, "intermediate production coordinates excluded"
                )
            )
            continue
        size = path.stat().st_size
        if size > max_file_bytes:
            omitted.append(
                OmittedFile(relative, size, f"file exceeds {max_file_bytes}-byte import limit")
            )
            continue
        if total + size > max_total_bytes:
            omitted.append(
                OmittedFile(relative, size, f"project exceeds {max_total_bytes}-byte import limit")
            )
            continue
        digest = _sha256(path)
        selected.append(LegacyFile(relative, size, digest, _category(path)))
        total += size

    manifest_payload = {
        "kind": kind,
        "source_name": root.name,
        "selected": [(f.relative_path, f.size_bytes, f.sha256) for f in selected],
        "omitted": [(f.relative_path, f.size_bytes, f.reason) for f in omitted],
        "metadata": metadata,
    }
    manifest_sha = hashlib.sha256(
        json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return LegacyImportPlan(
        kind=kind,
        source_root=root,
        source_name=root.name,
        manifest_sha256=manifest_sha,
        metadata=metadata,
        files=tuple(selected),
        omitted=tuple(omitted),
    )


def _read_project_config(path: Path, kind: LegacyKind) -> dict[str, str]:
    values: dict[str, str] = {}
    for _number, line in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(), 1
    ):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*\s*=\s*[^\n]*", stripped):
            continue
        key, raw = stripped.split("=", 1)
        key, value = key.strip(), raw.strip().strip("\"'")
        if key in _CONFIG_KEYS[kind]:
            values[key] = value
    return values


def _csv_summary(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = tuple(reader.fieldnames or ())
        rows = sum(1 for _ in reader)
    return {"columns": list(columns), "row_count": rows}


def _gromacs_versions(root: Path) -> list[str]:
    found: set[str] = set()
    for path in sorted(root.glob("*.log")):
        try:
            sample = path.read_text(encoding="utf-8", errors="replace")[: 128 * 1024]
        except OSError:
            continue
        found.update(match.group(1) for match in _VERSION.finditer(sample))
    return sorted(found)


def _mdp_observations(root: Path) -> dict[str, dict[str, str]]:
    observed: dict[str, dict[str, str]] = {}
    for path in sorted(root.glob("*.mdp")):
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            body = line.split(";", 1)[0].strip()
            if "=" in body:
                key, value = body.split("=", 1)
                values[key.strip()] = value.strip()
        observed[path.name] = values
    return observed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _category(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".conf", ".mdp", ".top", ".itp", ".ndx", ".yaml", ".yml"}:
        return "configuration_or_topology"
    if suffix in {".log", ".txt", ".md"}:
        return "log_or_documentation"
    if suffix in {".csv", ".dat", ".xvg", ".json"}:
        return "tabular_or_result"
    if suffix in {".pdb", ".pdbqt", ".sdf", ".mol2", ".gro", ".psf", ".crd"}:
        return "structure"
    return "other"
