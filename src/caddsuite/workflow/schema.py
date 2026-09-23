"""Committed JSON Schema for the workflow-definition file format."""

from __future__ import annotations

import json
from pathlib import Path

from caddsuite.workflow.definition import WorkflowDefinition


def render_workflow_schema() -> str:
    """Render the stable, reviewable schema document for workflow YAML/JSON."""
    schema = WorkflowDefinition.model_json_schema(mode="validation")
    schema["$id"] = "caddsuite://schemas/caddsuite.workflow/1"
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def export_workflow_schema(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "workflow_definition.schema.json"
    path.write_text(render_workflow_schema(), encoding="utf-8", newline="\n")
    return path


def diff_workflow_schema(out_dir: Path) -> list[str]:
    path = out_dir / "workflow_definition.schema.json"
    if not path.exists() or path.read_text(encoding="utf-8") != render_workflow_schema():
        return [path.name]
    return []
