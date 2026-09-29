from __future__ import annotations

import argparse
import csv
import hashlib
import json
import posixpath
import sys
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_key_for_source(
    source: str, map_path: Path, lock_packages: dict[str, Any]
) -> str | None:
    normalized = posixpath.normpath(posixpath.join(map_path.parent.as_posix(), source))
    prefix = "apps/web/"
    candidates = [key for key in lock_packages if key and normalized.startswith(prefix + key + "/")]
    return max(candidates, key=len) if candidates else None


def license_files(package_root: Path) -> list[Path]:
    prefixes = ("LICENSE", "LICENCE", "COPYING", "NOTICE")
    return sorted(
        path
        for path in package_root.iterdir()
        if path.is_file() and path.name.upper().startswith(prefixes)
    )


def write_inventory(web_root: Path, package_output: Path, asset_output: Path) -> tuple[int, int]:
    repo_root = web_root.parent.parent
    lock = json.loads((web_root / "package-lock.json").read_text(encoding="utf-8"))
    lock_packages: dict[str, Any] = lock.get("packages", {})
    maps = sorted((web_root / "dist/assets").glob("*.js.map"))
    if not maps:
        raise ValueError("No JavaScript source maps found; run npm exec vite -- build --sourcemap.")

    package_chunks: dict[str, set[str]] = {}
    for map_path in maps:
        source_map = json.loads(map_path.read_text(encoding="utf-8"))
        for source in source_map.get("sources", []):
            key = package_key_for_source(source, map_path.relative_to(repo_root), lock_packages)
            if key is not None:
                package_chunks.setdefault(key, set()).add(map_path.name.removesuffix(".map"))
            elif "/node_modules/" in source:
                raise ValueError(f"Mapped dependency is absent from package-lock.json: {source}")

    package_rows: list[dict[str, str]] = []
    missing: list[str] = []
    for key in sorted(package_chunks, key=str.casefold):
        locked = lock_packages[key]
        package_root = web_root / key
        manifest_path = package_root / "package.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = str(manifest.get("version", ""))
        if version != str(locked.get("version", "")):
            raise ValueError(
                f"Installed/locked version mismatch for {key}: {version} != {locked.get('version')}"
            )
        declared_license = manifest.get("license")
        if declared_license is None:
            missing.append(key)
            declared_license = ""
        files = license_files(package_root)
        if not files:
            missing.append(key + " (license text file missing)")
        package_rows.append(
            {
                "package_lock_path": key,
                "name": str(manifest.get("name", "")),
                "version": version,
                "declared_license_metadata": json.dumps(
                    declared_license, sort_keys=True, separators=(",", ":")
                ),
                "package_json_sha256": sha256(manifest_path),
                "license_files": ";".join(f"{path.name}:{sha256(path)}" for path in files),
                "js_chunks": ";".join(sorted(package_chunks[key])),
            }
        )
    if missing:
        raise ValueError("Missing license metadata or license text: " + ", ".join(missing))

    package_output.parent.mkdir(parents=True, exist_ok=True)
    with package_output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(package_rows[0]))
        writer.writeheader()
        writer.writerows(package_rows)

    assets = sorted(
        path
        for path in (web_root / "dist/assets").iterdir()
        if path.is_file() and not path.name.endswith(".map")
    )
    with asset_output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["asset", "bytes", "sha256"])
        writer.writeheader()
        for asset in assets:
            writer.writerow(
                {
                    "asset": asset.relative_to(repo_root).as_posix(),
                    "bytes": str(asset.stat().st_size),
                    "sha256": sha256(asset),
                }
            )
    return len(package_rows), len(assets)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventory packages represented in the built web JS bundle."
    )
    repo_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--web-root", type=Path, default=repo_root / "apps/web")
    parser.add_argument(
        "--package-output",
        type=Path,
        default=repo_root / "docs/release/licenses/WEB_BUNDLE_LICENSE_INVENTORY.csv",
    )
    parser.add_argument(
        "--asset-output",
        type=Path,
        default=repo_root / "docs/release/licenses/WEB_BUNDLE_ASSETS.csv",
    )
    args = parser.parse_args()
    try:
        package_count, asset_count = write_inventory(
            args.web_root.resolve(), args.package_output.resolve(), args.asset_output.resolve()
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"web bundle license inventory failed: {exc}", file=sys.stderr)
        return 2
    print(f"Recorded {package_count} mapped packages and {asset_count} emitted assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
