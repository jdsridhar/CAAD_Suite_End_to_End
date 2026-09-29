from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from scripts.release.audit_web_bundle_licenses import write_inventory


def _web_fixture(root: Path) -> tuple[Path, Path, Path]:
    web = root / "apps" / "web"
    assets = web / "dist" / "assets"
    package_root = web / "node_modules" / "fixture-package"
    assets.mkdir(parents=True)
    package_root.mkdir(parents=True)
    (web / "package-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "fixture-web"},
                    "node_modules/fixture-package": {"version": "1.2.3"},
                },
            }
        ),
        encoding="utf-8",
    )
    (package_root / "package.json").write_text(
        json.dumps({"name": "fixture-package", "version": "1.2.3", "license": "MIT"}),
        encoding="utf-8",
    )
    (package_root / "LICENSE").write_text("fixture license text\n", encoding="utf-8")
    (assets / "chunk.js").write_text("bundled bytes\n", encoding="utf-8")
    (assets / "chunk.js.map").write_text(
        json.dumps({"version": 3, "sources": ["../../node_modules/fixture-package/index.js"]}),
        encoding="utf-8",
    )
    (assets / "style.css").write_text("body{}\n", encoding="utf-8")
    return web, assets, package_root


def test_write_inventory_maps_locked_package_and_hashes_license_and_assets(tmp_path: Path) -> None:
    web, _assets, package_root = _web_fixture(tmp_path)
    package_output = tmp_path / "out" / "packages.csv"
    asset_output = tmp_path / "out" / "assets.csv"

    assert write_inventory(web, package_output, asset_output) == (1, 2)

    with package_output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["package_lock_path"] == "node_modules/fixture-package"
    assert rows[0]["version"] == "1.2.3"
    assert rows[0]["declared_license_metadata"] == '"MIT"'
    assert rows[0]["license_files"] == (
        "LICENSE:" + hashlib.sha256((package_root / "LICENSE").read_bytes()).hexdigest()
    )
    assert rows[0]["js_chunks"] == "chunk.js"

    with asset_output.open(encoding="utf-8", newline="") as stream:
        asset_rows = list(csv.DictReader(stream))
    assert {row["asset"] for row in asset_rows} == {
        "apps/web/dist/assets/chunk.js",
        "apps/web/dist/assets/style.css",
    }
    assert all(len(row["sha256"]) == 64 for row in asset_rows)


def test_write_inventory_rejects_installed_lock_version_mismatch(tmp_path: Path) -> None:
    web, _, _ = _web_fixture(tmp_path)
    lock_path = web / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["packages"]["node_modules/fixture-package"]["version"] = "9.9.9"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(ValueError, match="Installed/locked version mismatch"):
        write_inventory(
            web,
            tmp_path / "packages.csv",
            tmp_path / "assets.csv",
        )
