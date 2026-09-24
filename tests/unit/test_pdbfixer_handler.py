"""End-to-end stage-handler check including process logs and artifact registration."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.structure import PreparedReceptor, Structure, StructureSource
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade

ROOT = Path(__file__).resolve().parents[2]
PYFIXER_PYTHON = os.environ.get("CADDSUITE_PDBFIXER_PYTHON")
pytestmark = pytest.mark.skipif(
    not PYFIXER_PYTHON,
    reason="set CADDSUITE_PDBFIXER_PYTHON to run the isolated-engine integration test",
)


def test_handler_runs_worker_and_registers_normalized_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "platform.sqlite"
    upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    store = ArtifactStore(tmp_path / "artifact-store")
    source_blob = store.put_file(ROOT / "tests/data/golden/structure_g1/5NIU.cif")
    with sessions.begin() as session:
        source_row = register_blob(
            session,
            source_blob,
            kind="raw_structure_mmcif",
            media_type="chemical/x-mmcif",
            original_name="5NIU.cif",
        )
        source_id = source_row.id
    structure = Structure(
        id=new_ulid(),
        target_id=new_ulid(),
        source=StructureSource.RCSB,
        source_id="5NIU",
        entity_sequences={"1": "fixture sequence"},
        raw=ArtifactRef(
            artifact_id=source_id,
            role="raw_structure_mmcif",
            sha256=source_blob.sha256,
        ),
    )
    handler = PDBFixerPreparationHandler(
        python_executable=Path(PYFIXER_PYTHON),
        worker_script=ROOT / "src/caddsuite_worker/pdbfixer_worker.py",
        work_root=tmp_path / "jobs",
        log_root=tmp_path / "logs",
        engine_version="PDBFixer 1.12.0 / OpenMM 8.4",
        executor=LocalExecutor(store, sessions),
        artifact_store=store,
        sessions=sessions,
    )
    invocation = SimpleNamespace(
        task=SimpleNamespace(
            stage_id="prepare_protein",
            params={"selected_chain_ids": ["A"], "ph": 7.4},
        ),
        inputs={"structure": (structure,)},
    )
    try:
        result = handler.execute(invocation)
        assert isinstance(result, PreparedReceptor)
        assert result.selected_chain_ids == ("A",)
        assert result.artifacts["source_structure"].sha256 == source_blob.sha256
        assert store.verify(result.artifacts["prepared_structure"].sha256 or "")
        assert store.verify(result.artifacts["prepared_structure_pdb"].sha256 or "")
        assert store.verify(result.artifacts["worker_report"].sha256 or "")
        assert store.verify(result.artifacts["worker_request"].sha256 or "")
        assert result.output_residue_count == 126

        receptor_pdb = store.path_for(result.artifacts["prepared_structure_pdb"].sha256 or "")
        receptor_pdbqt = tmp_path / "meeko_receptor.pdbqt"
        receptor_json = tmp_path / "meeko_receptor.json"
        meeko = Path(PYFIXER_PYTHON).with_name("mk_prepare_receptor.py")
        meeko_run = subprocess.run(
            [
                str(meeko),
                "--read_pdb",
                str(receptor_pdb),
                "--write_pdbqt",
                str(receptor_pdbqt),
                "--write_json",
                str(receptor_json),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert meeko_run.returncode == 0, meeko_run.stderr
        assert receptor_pdbqt.stat().st_size > 0
        assert receptor_json.stat().st_size > 0
    finally:
        engine.dispose()
