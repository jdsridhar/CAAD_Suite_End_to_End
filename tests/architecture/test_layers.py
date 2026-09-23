"""Architectural fitness function: the layering rules of TARGET_ARCHITECTURE §3.

The contracts live in pyproject.toml ([tool.importlinter]). Examples: domain and contracts
never import storage or frameworks; the core never imports adapters; the engine-side
worker never imports the core. A violation fails the test suite, so the architecture
cannot erode silently.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_import_linter_contracts_hold(repo_root: Path) -> None:
    lint_imports = Path(sys.executable).parent / "lint-imports"
    result = subprocess.run(
        [str(lint_imports), "--no-cache"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BROKEN" not in result.stdout
