"""Export JSON Schemas for every registered contract.

The exported files in ``docs/schemas/`` are committed and checked by a test, so any
contract change shows up as a reviewable schema diff. They will also generate the
TypeScript types for the UI (ADR-0004, ADR-0009).
"""

from __future__ import annotations

import json
from pathlib import Path

import caddsuite.contracts  # noqa: F401  (registers all contracts)
from caddsuite.contracts.base import contract_registry

# Schemas owned by other layers share the docs/schemas folder, but have
# independent renderers to preserve the dependency direction.
_OTHER_SCHEMA_FILES = {"workflow_definition.schema.json"}


def render_schemas() -> dict[str, str]:
    """Return ``{filename: json_text}`` for every contract, deterministically."""
    rendered: dict[str, str] = {}
    index: dict[str, str] = {}
    for name, cls in sorted(contract_registry().items()):
        schema = cls.model_json_schema(mode="validation")
        schema["$id"] = f"caddsuite://schemas/{cls.schema_id()}"
        filename = f"{name}.schema.json"
        rendered[filename] = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        index[name] = cls.schema_id()
    rendered["index.json"] = json.dumps(index, indent=2, sort_keys=True) + "\n"
    return rendered


def export_schemas(out_dir: Path) -> list[Path]:
    """Write all schemas to ``out_dir`` (removing stale ``*.schema.json`` files)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_schemas()
    for stale in out_dir.glob("*.schema.json"):
        if stale.name not in rendered and stale.name not in _OTHER_SCHEMA_FILES:
            stale.unlink()
    written = []
    for filename, text in rendered.items():
        path = out_dir / filename
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def diff_schemas(out_dir: Path) -> list[str]:
    """Names of schema files that are missing or differ from the current contracts."""
    problems = []
    rendered = render_schemas()
    for filename, text in rendered.items():
        path = out_dir / filename
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            problems.append(filename)
    problems.extend(
        p.name
        for p in out_dir.glob("*.schema.json")
        if p.name not in rendered and p.name not in _OTHER_SCHEMA_FILES
    )
    return sorted(problems)
