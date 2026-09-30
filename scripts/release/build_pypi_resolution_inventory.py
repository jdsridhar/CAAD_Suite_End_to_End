"""Build a metadata-only license inventory from pip's reproducible install report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

LICENSE_FALLBACKS = {
    ("loguru", "0.7.3"): (
        "MIT",
        "PyPI 0.7.3 release page; wheel contains no license file",
    ),
    ("pathspec", "1.1.1"): (
        "MPL-2.0",
        "pathspec 1.1.1 wheel license file",
    ),
    ("markdown-it-py", "4.2.0"): (
        "MIT",
        "Official PyPI 4.2.0 release page; MIT classifier",
    ),
    ("mdurl", "0.1.2"): (
        "MIT",
        "Official executablebooks/mdurl LICENSE file",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metadata_text(value: str) -> str:
    """Normalize line-ending whitespace; original upstream metadata stays in pip report."""
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def metadata_license(metadata: dict[str, object]) -> tuple[str, str]:
    expression = metadata.get("license_expression")
    if isinstance(expression, str) and expression.strip():
        return expression.strip(), "PEP 639 License-Expression field"
    value = metadata.get("license")
    if isinstance(value, str) and value.strip():
        return metadata_text(
            value
        ), "License metadata field (whitespace-normalized; raw report retained)"
    classifiers = metadata.get("classifiers", [])
    if isinstance(classifiers, list):
        licenses = [x for x in classifiers if isinstance(x, str) and x.startswith("License ::")]
        if licenses:
            return "; ".join(licenses), "License classifier(s)"
    name = str(metadata.get("name", ""))
    version = str(metadata.get("version", ""))
    fallback = LICENSE_FALLBACKS.get((name.lower(), version))
    if fallback:
        return fallback
    return "UNRESOLVED", "No license expression, license field, or license classifier"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="pip install --report JSON")
    parser.add_argument("--output", type=Path, required=True, help="Output inventory CSV")
    parser.add_argument("--context", required=True, help="Resolution platform and source wheel")
    parser.add_argument(
        "--pathspec-wheel", type=Path, help="Exact pathspec wheel used for license fallback"
    )
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    rows = []
    seen: set[tuple[str, str]] = set()
    for install in report.get("install", []):
        metadata = install["metadata"]
        name, version = str(metadata["name"]), str(metadata["version"])
        key = (name.lower(), version)
        if key in seen:
            raise ValueError(f"Duplicate package resolution: {name} {version}")
        seen.add(key)
        license_value, source = metadata_license(metadata)
        archive_hash = (
            install.get("download_info", {})
            .get("archive_info", {})
            .get("hashes", {})
            .get("sha256", "")
        )
        rows.append(
            {
                "name": name,
                "version": version,
                "license_metadata": license_value,
                "metadata_source": source,
                "artifact_sha256": archive_hash,
                "resolution_context": args.context,
            }
        )

    pathspec = next(
        (r for r in rows if r["name"].lower() == "pathspec" and r["version"] == "1.1.1"), None
    )
    if pathspec and args.pathspec_wheel:
        with ZipFile(args.pathspec_wheel) as wheel:
            names = [
                n for n in wheel.namelist() if n.lower().endswith(".dist-info/licenses/license")
            ]
            if (
                len(names) != 1
                or b"Mozilla Public License Version 2.0" not in wheel.read(names[0])[:100]
            ):
                raise ValueError("Expected MPL-2.0 license text not found in exact pathspec wheel")
        if (
            pathspec["artifact_sha256"]
            and sha256(args.pathspec_wheel) != pathspec["artifact_sha256"]
        ):
            raise ValueError("pathspec wheel SHA-256 differs from pip resolution report")
        pathspec["metadata_source"] += f"; SHA-256 checked: {sha256(args.pathspec_wheel)}"

    rows.sort(key=lambda row: (row["name"].lower(), row["version"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    unresolved = [row for row in rows if row["license_metadata"] == "UNRESOLVED"]
    print(f"packages={len(rows)} unresolved={len(unresolved)} report_sha256={sha256(args.report)}")
    for row in unresolved:
        print(f"UNRESOLVED {row['name']}=={row['version']}")
    return 2 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
