"""PDBFixer stage handler: process isolation, artifact capture, and normalization."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.structure import PreparedReceptor, Structure
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.structure.prepare_protein import (
    normalize_pdbfixer_result,
    plan_pdbfixer_command,
    write_pdbfixer_request,
)
from caddsuite.workflow.scheduler import (
    StageExecutionFailure,
    TaskInvocation,
)


class PDBFixerPreparationHandler:
    """Execute selected-chain protein preparation with a foreign-env PDBFixer worker."""

    adapter_id = "structure.prepare_protein.pdbfixer"
    adapter_version = "1.1.0"

    def __init__(
        self,
        *,
        python_executable: Path,
        worker_script: Path,
        work_root: Path,
        log_root: Path,
        engine_version: str,
        executor: LocalExecutor,
        artifact_store: ArtifactStore,
        sessions: sessionmaker[Session],
    ) -> None:
        self.python_executable = python_executable.resolve(strict=True)
        self.worker_script = worker_script.resolve(strict=True)
        self.work_root = work_root.resolve()
        self.log_root = log_root.resolve()
        self.engine_version = engine_version
        self.executor = executor
        self.artifact_store = artifact_store
        self.sessions = sessions
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if not isinstance(value, Structure):
            raise TypeError(
                f"protein preparation fan-out requires Structure, got {type(value).__name__}"
            )
        return str(value.id)

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        structure = self._structure_input(inputs)
        if structure.raw.sha256 is None:
            raise ValueError("source structure artifact has no digest")
        return {"source_structure": structure.raw.sha256}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        structure = self._structure_input(inputs)
        return (
            {
                "structure.source_id": structure.source_id or "",
                "structure.has_sequence": bool(structure.entity_sequences),
            },
            frozenset({"structure.source_id", "structure.has_sequence"}),
        )

    def execute(self, invocation: TaskInvocation) -> PreparedReceptor:
        structure = self._structure_input(invocation.inputs)
        if structure.raw.sha256 is None or not self.artifact_store.verify(structure.raw.sha256):
            raise StageExecutionFailure(
                "STRUCTURE.SOURCE_ARTIFACT_INVALID",
                "Source mmCIF artifact is missing or its SHA-256 does not match; "
                "restore the exact input artifact.",
            )
        params = invocation.task.params
        chains = params.get("selected_chain_ids")
        if not isinstance(chains, (tuple, list)) or any(
            not isinstance(item, str) for item in chains
        ):
            raise StageExecutionFailure(
                "STRUCTURE.CHAIN_SELECTION_REQUIRED",
                "Set selected_chain_ids to the explicitly resolved receptor chain IDs.",
            )
        ph_value = params.get("ph")
        if not isinstance(ph_value, (int, float)) or isinstance(ph_value, bool):
            raise StageExecutionFailure(
                "STRUCTURE.PH_REQUIRED", "Set an explicit numeric protein preparation pH."
            )
        ph = float(ph_value)

        stage_dir = self.work_root / f"{invocation.task.stage_id}-{new_ulid()}"
        stage_dir.mkdir(mode=0o700)
        source = self.artifact_store.path_for(structure.raw.sha256)
        output = stage_dir / "prepared_receptor.cif"
        pdb_output = stage_dir / "prepared_receptor.pdb"
        request = write_pdbfixer_request(
            source_mmcif=source,
            output_mmcif=output,
            output_pdb=pdb_output,
            request_path=stage_dir / "worker_request.json",
            work_dir=stage_dir,
            selected_chain_ids=tuple(chains),
            ph=ph,
            fill_internal_gaps=bool(params.get("fill_internal_gaps", True)),
            keep_water=bool(params.get("keep_water", False)),
        )
        command = plan_pdbfixer_command(
            python_executable=self.python_executable,
            worker_script=self.worker_script,
            request_path=request,
            work_dir=stage_dir,
        )
        execution = self.executor.start(command, log_dir=self.log_root).wait()
        # LocalExecutor stores stdout/stderr as content-addressed artifacts.
        if execution.exit_code != 0:
            stderr = self._artifact_text(execution.stderr, limit=4000)
            raise StageExecutionFailure(
                "STRUCTURE.PREPARATION_FAILED",
                f"PDBFixer exited with status {execution.exit_code}: "
                f"{stderr or 'see task stderr artifact'}",
            )
        stdout = self._artifact_text(execution.stdout, limit=2_000_000)
        try:
            response = cast(dict[str, Any], json.loads(stdout))
        except (json.JSONDecodeError, TypeError) as exc:
            raise StageExecutionFailure(
                "STRUCTURE.INVALID_WORKER_RESPONSE",
                f"PDBFixer stdout is not a JSON worker response: {exc}",
            ) from exc
        if not output.is_file() or not pdb_output.is_file():
            raise StageExecutionFailure(
                "STRUCTURE.OUTPUT_MISSING",
                "PDBFixer reported success but did not produce both prepared mmCIF"
                " and PDB outputs.",
            )

        prepared_ref = self._register_file(
            output, kind="prepared_receptor_mmcif", media_type="chemical/x-mmcif"
        )
        prepared_pdb_ref = self._register_file(
            pdb_output, kind="prepared_receptor_pdb", media_type="chemical/x-pdb"
        )
        request_ref = self._register_file(
            request, kind="worker_request", media_type="application/json"
        )
        return normalize_pdbfixer_result(
            response,
            structure=structure,
            selected_chain_ids=tuple(chains),
            ph=ph,
            prepared_artifact=prepared_ref,
            prepared_pdb_artifact=prepared_pdb_ref,
            report_artifact=execution.stdout,
            request_artifact=request_ref,
            stderr_artifact=execution.stderr,
        )

    def _structure_input(self, inputs: Mapping[str, tuple[VersionedContract, ...]]) -> Structure:
        matches = [
            value for group in inputs.values() for value in group if isinstance(value, Structure)
        ]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one Structure input, received {len(matches)}")
        return matches[0]

    def _register_file(self, path: Path, *, kind: str, media_type: str) -> ArtifactRef:
        blob = self.artifact_store.put_file(path)
        with self.sessions.begin() as session:
            row = register_blob(
                session,
                blob,
                kind=kind,
                media_type=media_type,
                original_name=path.name,
            )
            artifact_id = row.id
        return ArtifactRef(artifact_id=artifact_id, role=kind, sha256=blob.sha256)

    def _artifact_text(self, artifact: ArtifactRef, *, limit: int) -> str:
        if artifact.sha256 is None:
            return ""
        path = self.artifact_store.path_for(artifact.sha256)
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except OSError:
            return ""
