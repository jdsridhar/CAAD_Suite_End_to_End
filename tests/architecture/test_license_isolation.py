"""ADR-0013: platform code never imports GPL-licensed libraries in-process.

GPL tools (Open Babel, PLIP, ...) are run as separate programs. Process isolation
(ADR-0002) doubles as license isolation. This AST scan enforces the rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_TOP_LEVEL = {"openbabel", "pybel", "plip", "PyQt5", "PyQt6"}


def _imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_no_gpl_library_is_imported_by_platform_code(repo_root: Path) -> None:
    offenders = []
    for package in ("caddsuite", "caddsuite_worker"):
        for path in sorted((repo_root / "src" / package).rglob("*.py")):
            bad = _imported_top_levels(path) & FORBIDDEN_TOP_LEVEL
            if bad:
                offenders.append(f"{path.relative_to(repo_root)}: {sorted(bad)}")
    assert not offenders, "GPL imports (run the tool as a subprocess instead):\n" + "\n".join(
        offenders
    )
