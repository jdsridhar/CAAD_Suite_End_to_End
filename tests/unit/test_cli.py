"""CLI smoke tests (the CLI is a thin layer; logic is tested in the unit tests)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import caddsuite
from caddsuite.cli.main import app

runner = CliRunner()


def test_version_reports_platform_and_git_state() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["version"] == caddsuite.__version__


def test_db_upgrade_creates_database(tmp_path: Path) -> None:
    result = runner.invoke(app, ["db", "upgrade", "--data-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "caddsuite.db").exists()
    assert "revision 0006" in result.output


def test_host_info_is_json() -> None:
    result = runner.invoke(app, ["host-info"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["logical_cpus"] >= 1


def test_schemas_check_passes_on_committed_schemas(repo_root: Path) -> None:
    result = runner.invoke(app, ["schemas", "check", "--out", str(repo_root / "docs" / "schemas")])
    assert result.exit_code == 0, result.output


def test_env_snapshot_of_running_env() -> None:
    if not (Path(sys.prefix) / "conda-meta").is_dir():
        pytest.skip("not running inside a conda environment")
    result = runner.invoke(app, ["env-snapshot", sys.prefix])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)["lock_sha256"]) == 64
