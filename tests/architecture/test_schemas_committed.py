"""Committed JSON Schemas must match the contracts.

A contract change therefore always appears as a reviewable diff in ``docs/schemas/``.
To refresh the schemas: ``caddsuite schemas export``.
"""

from __future__ import annotations

from pathlib import Path

from caddsuite.contracts.schema_export import diff_schemas


def test_committed_schemas_are_current(repo_root: Path) -> None:
    problems = diff_schemas(repo_root / "docs" / "schemas")
    assert not problems, f"out-of-date schemas {problems}; run `caddsuite schemas export`"
