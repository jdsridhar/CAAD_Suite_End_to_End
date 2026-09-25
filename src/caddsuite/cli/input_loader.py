"""Load versioned workflow contracts and bind their file artifacts safely."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.base import ArtifactRef, VersionedContract, load_contract
from caddsuite.storage.artifacts import ArtifactStore, register_blob


def load_workflow_inputs(
    manifest_path: Path,
    *,
    declarations: dict[str, str],
    sessions: sessionmaker[Session],
    artifacts: ArtifactStore,
) -> dict[str, VersionedContract | tuple[VersionedContract, ...]]:
    """Deserialize declared contracts and ingest each referenced artifact file.

    Manifest format: ``{"inputs": {name: contract-or-list}, "artifacts": {artifact_id: path}}``.
    Relative artifact paths resolve beside the manifest; bytes are content-addressed and
    the normalized contracts are rewritten to the registered artifact IDs and hashes.
    """
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) - {"inputs", "artifacts"}:
        raise ValueError("input manifest must contain only 'inputs' and optional 'artifacts'")
    raw_inputs = payload.get("inputs")
    raw_artifacts = payload.get("artifacts", {})
    if not isinstance(raw_inputs, dict) or not isinstance(raw_artifacts, dict):
        raise ValueError("manifest 'inputs' and 'artifacts' must be JSON objects")
    if set(raw_inputs) != set(declarations):
        raise ValueError(
            "manifest inputs must exactly match workflow declarations; "
            f"expected {sorted(declarations)}, got {sorted(raw_inputs)}"
        )
    paths: dict[str, Path] = {}
    for artifact_id, raw_path in raw_artifacts.items():
        if not isinstance(artifact_id, str) or not isinstance(raw_path, str):
            raise ValueError("artifact attachment keys and paths must be strings")
        path = Path(raw_path)
        if not path.is_absolute():
            path = manifest_path.parent / path
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"artifact attachment is not a regular file: {resolved}")
        paths[artifact_id] = resolved

    ingested: dict[str, ArtifactRef] = {}

    def bind(value: Any) -> Any:
        if isinstance(value, ArtifactRef):
            key = str(value.artifact_id)
            if key not in paths:
                raise ValueError(f"artifact {key} has no file attachment in manifest")
            if key not in ingested:
                blob = artifacts.put_file(paths[key])
                if value.sha256 is not None and value.sha256 != blob.sha256:
                    raise ValueError(f"artifact {key} SHA-256 does not match attached file")
                with sessions.begin() as session:
                    row = register_blob(
                        session,
                        blob,
                        kind="workflow_input",
                        media_type="application/octet-stream",
                        original_name=paths[key].name,
                    )
                ingested[key] = ArtifactRef(artifact_id=row.id, role=value.role, sha256=row.sha256)
            return ingested[key]
        if isinstance(value, BaseModel):
            updates = {name: bind(getattr(value, name)) for name in type(value).model_fields}
            return value.model_copy(update=updates)
        if isinstance(value, dict):
            return {key: bind(child) for key, child in value.items()}
        if isinstance(value, (tuple, list)):
            return type(value)(bind(child) for child in value)
        return value

    loaded: dict[str, VersionedContract | tuple[VersionedContract, ...]] = {}
    for name, declaration in declarations.items():
        values = raw_inputs[name] if isinstance(raw_inputs[name], list) else [raw_inputs[name]]
        contracts: list[VersionedContract] = []
        for item in values:
            if not isinstance(item, dict):
                raise ValueError(f"workflow input {name!r} must contain contract objects")
            contract = load_contract(item)
            if contract.schema_id() != declaration:
                raise ValueError(
                    f"workflow input {name!r} declares {declaration}, got {contract.schema_id()}"
                )
            contracts.append(bind(contract))
        loaded[name] = tuple(contracts) if isinstance(raw_inputs[name], list) else contracts[0]
    unused = set(paths) - set(ingested)
    if unused:
        raise ValueError(f"manifest attaches unused artifact IDs: {sorted(unused)}")
    return loaded
