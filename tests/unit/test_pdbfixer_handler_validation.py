from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.registry import InputRecord
from caddsuite.contracts.structure import Structure, StructureSource
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.workflow.scheduler import StageExecutionFailure


@pytest.fixture
def handler(tmp_path: Path) -> tuple[PDBFixerPreparationHandler, ArtifactStore]:
    python = tmp_path / "python"
    worker = tmp_path / "worker.py"
    python.write_text("", encoding="utf-8")
    worker.write_text("", encoding="utf-8")
    database = tmp_path / "platform.sqlite"
    upgrade(database)
    engine = create_db_engine(database)
    sessions = make_session_factory(engine)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    value = PDBFixerPreparationHandler(
        python_executable=python,
        worker_script=worker,
        work_root=tmp_path / "jobs",
        log_root=tmp_path / "logs",
        engine_version="fixture-only",
        executor=LocalExecutor(artifacts, sessions),
        artifact_store=artifacts,
        sessions=sessions,
    )
    yield value, artifacts
    engine.dispose()


def _structure(artifacts: ArtifactStore, *, with_hash: bool = True) -> Structure:
    blob = artifacts.put_bytes(b"small structure fixture")
    return Structure(
        id=new_ulid(),
        target_id=new_ulid(),
        source=StructureSource.LOCAL,
        source_id="fixture",
        entity_sequences={"A": "AG"},
        raw=ArtifactRef(
            artifact_id=new_ulid(),
            role="source_structure",
            sha256=blob.sha256 if with_hash else None,
        ),
    )


def test_input_identity_hash_and_gate_metadata(handler) -> None:
    instance, artifacts = handler
    structure = _structure(artifacts)
    inputs = {"structure": (structure,)}

    assert instance.subject_key("structure", structure) == str(structure.id)
    assert instance.artifact_hashes(inputs) == {"source_structure": structure.raw.sha256}
    context, fields = instance.gate_context(inputs)
    assert context == {"structure.source_id": "fixture", "structure.has_sequence": True}
    assert fields == {"structure.source_id", "structure.has_sequence"}
    with pytest.raises(TypeError, match="requires Structure"):
        instance.subject_key("structure", InputRecord(source="manual", original_text="CCO"))
    with pytest.raises(ValueError, match="exactly one Structure"):
        instance.artifact_hashes({})
    with pytest.raises(ValueError, match="no digest"):
        instance.artifact_hashes({"structure": (_structure(artifacts, with_hash=False),)})


@pytest.mark.parametrize(
    ("parameters", "error_code"),
    [
        ({}, "STRUCTURE.CHAIN_SELECTION_REQUIRED"),
        ({"selected_chain_ids": ["A"]}, "STRUCTURE.PH_REQUIRED"),
        ({"selected_chain_ids": ["A"], "ph": True}, "STRUCTURE.PH_REQUIRED"),
    ],
)
def test_execute_requires_registered_source_explicit_chain_and_numeric_ph(
    handler, parameters: dict[str, object], error_code: str
) -> None:
    instance, artifacts = handler
    structure = _structure(artifacts)
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="prepare", params=parameters),
        inputs={"structure": (structure,)},
    )

    with pytest.raises(StageExecutionFailure) as exc:
        instance.execute(invocation)

    assert exc.value.code == error_code


def test_execute_rejects_source_hash_that_is_not_in_the_store(handler) -> None:
    instance, artifacts = handler
    structure = _structure(artifacts).model_copy(
        update={"raw": ArtifactRef(artifact_id=new_ulid(), role="missing", sha256="f" * 64)}
    )
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="prepare", params={"selected_chain_ids": ["A"], "ph": 7.4}),
        inputs={"structure": (structure,)},
    )

    with pytest.raises(StageExecutionFailure) as exc:
        instance.execute(invocation)

    assert exc.value.code == "STRUCTURE.SOURCE_ARTIFACT_INVALID"
