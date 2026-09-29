from __future__ import annotations

import json
from pathlib import Path

import pytest

from caddsuite.adapters.system_builders.amber_handler import AmberTLeapBuilderHandler
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildRequest
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.workflow.scheduler import StageExecutionFailure


def _request(**source_artifacts: ArtifactRef) -> SystemBuildRequest:
    return SystemBuildRequest(
        id=new_ulid(),
        complex_id=new_ulid(),
        compound_id=new_ulid(),
        form_id=new_ulid(),
        target_id=new_ulid(),
        pose_id=new_ulid(),
        source_artifacts=source_artifacts,
        mode="build",
        parameters={"force_field": "amber14sb"},
    )


def _complex() -> Complex:
    return Complex(
        id=new_ulid(),
        compound_id=new_ulid(),
        form_id=new_ulid(),
        target_id=new_ulid(),
        structure_id=new_ulid(),
        prepared_receptor_id=new_ulid(),
        docking_run_id=new_ulid(),
        pose_id=new_ulid(),
        protein=ArtifactRef(artifact_id=new_ulid(), role="protein", sha256="a" * 64),
        ligand=ArtifactRef(artifact_id=new_ulid(), role="ligand", sha256="b" * 64),
        assembled=ArtifactRef(artifact_id=new_ulid(), role="assembled", sha256="c" * 64),
        protein_atom_count=10,
        ligand_atom_count=5,
        ligand_heavy_atom_count=3,
        coordinate_fidelity_max_dev_A=0.0,
    )


def _bare_handler(store: ArtifactStore) -> AmberTLeapBuilderHandler:
    handler = object.__new__(AmberTLeapBuilderHandler)
    handler.artifact_store = store
    return handler


def test_handler_identity_source_hashes_and_gate_context(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    blob = store.put_bytes(b"source coordinates")
    source = ArtifactRef(artifact_id=new_ulid(), role="protein", sha256=blob.sha256)
    request = _request(**{"inputs/protein.pdb": source})
    handler = _bare_handler(store)
    complex_model = _complex()

    assert handler.subject_key("complex", complex_model) == str(complex_model.id)
    assert handler.subject_key("complex", request) == str(request.complex_id)
    assert handler.artifact_hashes({"request": (request,)}) == {
        "source:inputs/protein.pdb": blob.sha256
    }
    context, fields = handler.gate_context({"request": (request,)})
    assert context == {"system_build.mode": "build", "system_build.adapter": handler.adapter_id}
    assert fields == {"system_build.mode", "system_build.adapter"}
    with pytest.raises(TypeError, match="requires a Complex or request"):
        handler.subject_key("complex", source)
    with pytest.raises(ValueError, match="no SHA-256"):
        handler.artifact_hashes(
            {
                "request": (
                    _request(**{"inputs/protein.pdb": source.model_copy(update={"sha256": None})}),
                )
            }
        )


def test_materialize_inputs_checks_relative_paths_hashes_and_collisions(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    blob = store.put_bytes(b"source coordinates")
    reference = ArtifactRef(artifact_id=new_ulid(), role="protein", sha256=blob.sha256)
    request = _request(**{"inputs/protein.pdb": reference})
    stage = tmp_path / "stage"
    stage.mkdir()
    handler = _bare_handler(store)

    handler._materialize_inputs(request, stage)
    destination = stage / "inputs/protein.pdb"
    assert destination.read_bytes() == b"source coordinates"

    collision_stage = tmp_path / "collision"
    collision_stage.mkdir()
    (collision_stage / "inputs").mkdir()
    (collision_stage / "inputs/protein.pdb").touch()
    with pytest.raises(StageExecutionFailure) as collision:
        handler._materialize_inputs(request, collision_stage)
    assert collision.value.code == "AMBER_BUILD.INPUT_PATH_COLLISION"

    unsafe = _request(**{"../outside.pdb": reference})
    with pytest.raises(StageExecutionFailure) as traversal:
        handler._materialize_inputs(unsafe, tmp_path / "unsafe")
    assert traversal.value.code == "AMBER_BUILD.UNSAFE_PATH"

    missing_hash = _request(**{"protein.pdb": reference.model_copy(update={"sha256": "f" * 64})})
    with pytest.raises(StageExecutionFailure) as missing:
        handler._materialize_inputs(missing_hash, tmp_path / "missing")
    assert missing.value.code == "AMBER_BUILD.INPUT_ARTIFACT_INVALID"


def test_worker_failure_prefers_structured_error_then_stderr(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    handler = _bare_handler(store)
    stage = tmp_path / "stage"
    (stage / "amber_outputs").mkdir(parents=True)
    (stage / "amber_outputs/worker_result.json").write_text(
        json.dumps({"error_code": "AMBER_BUILD.MISSING_PARAMETER", "error": "No frcmod"}),
        encoding="utf-8",
    )
    stderr = store.put_bytes(b"long stderr details")

    assert handler._failure_message(
        stage, ArtifactRef(artifact_id=new_ulid(), role="stderr", sha256=stderr.sha256)
    ) == (
        "AMBER_BUILD.MISSING_PARAMETER",
        "No frcmod",
    )
    (stage / "amber_outputs/worker_result.json").write_text("{broken", encoding="utf-8")
    code, message = handler._failure_message(
        stage, ArtifactRef(artifact_id=new_ulid(), role="stderr", sha256=stderr.sha256)
    )
    assert code == "AMBER_BUILD.WORKER_FAILED"
    assert "long stderr details" in message
    assert (
        AmberTLeapBuilderHandler._media_type(Path("system.prmtop")) == "chemical/x-amber-topology"
    )
    assert AmberTLeapBuilderHandler._media_type(Path("opaque.bin")) == "application/octet-stream"


@pytest.mark.parametrize("stderr_text", ["", "x" * 5000])
def test_worker_failure_without_report_uses_bounded_stderr_detail(
    tmp_path: Path, stderr_text: str
) -> None:
    store = ArtifactStore(tmp_path / "store")
    handler = _bare_handler(store)
    stage = tmp_path / "missing-report"
    stage.mkdir()
    stderr = store.put_bytes(stderr_text.encode())

    code, message = handler._failure_message(
        stage, ArtifactRef(artifact_id=new_ulid(), role="stderr", sha256=stderr.sha256)
    )

    assert code == "AMBER_BUILD.WORKER_FAILED"
    if stderr_text:
        assert message.endswith("x" * 4000)
        assert "x" * 4001 not in message
    else:
        assert message.endswith("outputs. ")


def test_worker_failure_unreadable_report_falls_back_to_stderr(tmp_path: Path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path / "store")
    handler = _bare_handler(store)
    stage = tmp_path / "unreadable-report"
    output_dir = stage / "amber_outputs"
    output_dir.mkdir(parents=True)
    report_path = output_dir / "worker_result.json"
    report_path.write_text("{}", encoding="utf-8")
    stderr = store.put_bytes(b"worker diagnostic")
    original_read_text = Path.read_text

    def fail_report_read(path: Path, *args, **kwargs):
        if path == report_path:
            raise OSError("simulated unreadable report")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_report_read)
    code, message = handler._failure_message(
        stage, ArtifactRef(artifact_id=new_ulid(), role="stderr", sha256=stderr.sha256)
    )

    assert code == "AMBER_BUILD.WORKER_FAILED"
    assert "worker diagnostic" in message


def test_handler_success_stages_worker_outputs_and_normalizes_registered_artifacts(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from caddsuite.storage.db import create_db_engine, make_session_factory
    from caddsuite.storage.migrate import upgrade

    db_path = tmp_path / "platform.sqlite"
    upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    store = ArtifactStore(tmp_path / "store")
    complex_model = _complex()
    source_blob = store.put_bytes(b"source protein")
    source = ArtifactRef(artifact_id=new_ulid(), role="protein", sha256=source_blob.sha256)
    request = _request(**{"inputs/protein.pdb": source}).model_copy(
        update={"complex_id": complex_model.id}
    )
    stdout_blob = store.put_bytes(b"fake worker stdout")
    stderr_blob = store.put_bytes(b"")
    normalized = object()

    class FakeAdapter:
        def __init__(self):
            self.normalized_inputs = None

        def validate_input(self, context):
            assert context.working_directory.is_dir()
            return ()

        def plan(self, context):
            command = SimpleNamespace(
                argv=("fake-amber-worker",),
                working_directory=context.working_directory,
                environment={},
            )
            return SimpleNamespace(commands=(command,))

        def normalize_result(self, artifacts, context):
            self.normalized_inputs = (artifacts, context)
            return normalized

    class FakeExecutor:
        def start(self, command, *, log_dir):
            assert command.argv == ("fake-amber-worker",)
            assert log_dir.is_dir()
            stage_dir = command.cwd
            (stage_dir / "amber_worker_request.json").write_text("{}", encoding="utf-8")
            output_dir = stage_dir / "amber_outputs"
            output_dir.mkdir()
            (output_dir / "worker_result.json").write_text('{"status":"fixture"}', encoding="utf-8")
            (output_dir / "system.prmtop").write_bytes(b"fixture topology")
            return SimpleNamespace(
                wait=lambda: SimpleNamespace(
                    exit_code=0,
                    stdout=ArtifactRef(
                        artifact_id=new_ulid(), role="stdout", sha256=stdout_blob.sha256
                    ),
                    stderr=ArtifactRef(
                        artifact_id=new_ulid(), role="stderr", sha256=stderr_blob.sha256
                    ),
                )
            )

    adapter = FakeAdapter()
    handler = AmberTLeapBuilderHandler(
        adapter=adapter,
        work_root=tmp_path / "jobs",
        log_root=tmp_path / "logs",
        engine_version="fixture worker only",
        executor=FakeExecutor(),
        artifact_store=store,
        sessions=sessions,
    )
    invocation = SimpleNamespace(
        task=SimpleNamespace(stage_id="amber_build", params={}),
        inputs={"request": (request,), "complex": (complex_model,)},
    )
    try:
        assert handler.execute(invocation) is normalized
        assert adapter.normalized_inputs is not None
        raw_outputs, context = adapter.normalized_inputs
        assert context.inputs["request"] == request
        assert {"amber_worker_request.json", "execution/stdout.log", "execution/stderr.log"} <= set(
            raw_outputs
        )
        assert "amber_outputs/worker_result.json" in raw_outputs
        assert "amber_outputs/system.prmtop" in raw_outputs
        for ref in raw_outputs.values():
            if ref.sha256 is not None and ref.role != "stdout" and ref.role != "stderr":
                assert store.verify(ref.sha256)
    finally:
        engine.dispose()
