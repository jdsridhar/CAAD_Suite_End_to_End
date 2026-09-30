from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPO_ROOT / "scripts" / "release" / "build_pypi_resolution_inventory.py"


def run_builder(
    tmp_path: Path,
    entries: list[dict[str, object]],
    *,
    pathspec_wheel: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"install": entries}), encoding="utf-8")
    output = tmp_path / "inventory.csv"
    command = [
        sys.executable,
        str(BUILDER),
        "--report",
        str(report),
        "--output",
        str(output),
        "--context",
        "test fixture",
    ]
    if pathspec_wheel is not None:
        command.extend(["--pathspec-wheel", str(pathspec_wheel)])
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return result


def entry(
    name: str,
    version: str,
    metadata: dict[str, object],
    *,
    sha256: str = "",
) -> dict[str, object]:
    return {
        "metadata": {"name": name, "version": version, **metadata},
        "download_info": {"archive_info": {"hashes": {"sha256": sha256}}},
    }


def read_inventory(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return {row["name"]: row for row in csv.DictReader(stream)}


def test_inventory_metadata_fallbacks_and_unresolved_status(tmp_path: Path) -> None:
    entries = [
        entry("expression", "1.0", {"license_expression": "MIT"}),
        entry("raw-license", "1.0", {"license": "Terms\n  Conditions  \n"}),
        entry(
            "classifier-only",
            "1.0",
            {"classifiers": ["License :: OSI Approved :: BSD License"]},
        ),
        entry("loguru", "0.7.3", {}),
        entry("markdown-it-py", "4.2.0", {}),
        entry("mdurl", "0.1.2", {}),
        entry("unknown", "9.9", {}),
    ]

    result = run_builder(tmp_path, entries)

    assert result.returncode == 2
    assert "packages=7 unresolved=1" in result.stdout
    assert "UNRESOLVED unknown==9.9" in result.stdout
    rows = read_inventory(tmp_path / "inventory.csv")
    assert rows["expression"]["license_metadata"] == "MIT"
    assert rows["expression"]["metadata_source"] == "PEP 639 License-Expression field"
    assert rows["raw-license"]["license_metadata"] == "Terms\n  Conditions"
    assert rows["classifier-only"]["license_metadata"] == "License :: OSI Approved :: BSD License"
    assert rows["loguru"]["license_metadata"] == "MIT"
    assert rows["markdown-it-py"]["license_metadata"] == "MIT"
    assert rows["mdurl"]["license_metadata"] == "MIT"
    assert rows["unknown"]["license_metadata"] == "UNRESOLVED"


def make_pathspec_wheel(path: Path) -> str:
    license_text = b"Mozilla Public License Version 2.0\n" + b"terms\n"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as wheel:
        wheel.writestr("pathspec-1.1.1.dist-info/licenses/LICENSE", license_text)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pathspec_fallback_requires_matching_wheel_hash(tmp_path: Path) -> None:
    wheel_path = tmp_path / "pathspec-1.1.1-py3-none-any.whl"
    wheel_hash = make_pathspec_wheel(wheel_path)
    report_entry = entry("pathspec", "1.1.1", {}, sha256=wheel_hash)

    result = run_builder(tmp_path, [report_entry], pathspec_wheel=wheel_path)

    assert result.returncode == 0
    row = read_inventory(tmp_path / "inventory.csv")["pathspec"]
    assert row["license_metadata"] == "MPL-2.0"
    assert row["artifact_sha256"] == wheel_hash
    assert "SHA-256 checked" in row["metadata_source"]


def test_pathspec_rejects_wheel_that_differs_from_resolution_report(tmp_path: Path) -> None:
    wheel_path = tmp_path / "pathspec-1.1.1-py3-none-any.whl"
    make_pathspec_wheel(wheel_path)
    report_entry = entry("pathspec", "1.1.1", {}, sha256="0" * 64)

    result = run_builder(tmp_path, [report_entry], pathspec_wheel=wheel_path)

    assert result.returncode != 0
    assert "pathspec wheel SHA-256 differs from pip resolution report" in result.stderr
