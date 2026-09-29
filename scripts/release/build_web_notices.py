from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path


def build_notices(inventory: Path, web_root: Path, output: Path) -> int:
    blocks: list[str] = [
        "CADD Suite web bundle third-party license texts",
        "Generated from the source-map inventory. Review before distribution; "
        "this file is not legal clearance.",
        "",
    ]
    count = 0
    with inventory.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            package_root = (web_root / row["package_lock_path"]).resolve()
            if not package_root.is_relative_to(web_root.resolve()):
                raise ValueError(f"Package path escapes web root: {row['package_lock_path']}")
            manifest_path = package_root / "package.json"
            manifest_bytes = manifest_path.read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != row["package_json_sha256"]:
                raise ValueError(f"Package manifest hash changed: {row['name']}")
            manifest = json.loads(manifest_bytes)
            if str(manifest.get("version", "")) != row["version"]:
                raise ValueError(f"Package version changed: {row['name']}")
            for entry in filter(None, row["license_files"].split(";")):
                name, expected_hash = entry.rsplit(":", 1)
                license_path = (package_root / name).resolve()
                if not license_path.is_relative_to(package_root):
                    raise ValueError(f"License path escapes package root: {name}")
                raw = license_path.read_bytes()
                actual_hash = hashlib.sha256(raw).hexdigest()
                if actual_hash != expected_hash:
                    raise ValueError(f"License file hash changed: {row['name']} {name}")
                text = raw.decode("utf-8")
                blocks.extend(
                    [
                        "=" * 78,
                        f"{row['name']} {row['version']} - {name}",
                        f"Declared license metadata: {row['declared_license_metadata']}",
                        f"SHA-256: {actual_hash}",
                        "=" * 78,
                        text.rstrip("\n"),
                        "",
                    ]
                )
                count += 1
    if count == 0:
        raise ValueError("The inventory contains no license or notice files.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    return count


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Assemble a hash-verified candidate web bundle notices file."
    )
    parser.add_argument("--web-root", type=Path, default=repo_root / "apps/web")
    parser.add_argument(
        "--inventory",
        type=Path,
        default=repo_root / "docs/release/licenses/WEB_BUNDLE_LICENSE_INVENTORY.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "docs/release/licenses/WEB_BUNDLE_THIRD_PARTY_NOTICES.txt",
    )
    args = parser.parse_args()
    try:
        count = build_notices(
            args.inventory.resolve(), args.web_root.resolve(), args.output.resolve()
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"web third-party notices generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Assembled {count} hash-verified license/notice texts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
