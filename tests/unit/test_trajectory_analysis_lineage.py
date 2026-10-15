"""Derived plots must prove the processing/MD source chain before matching raw files."""

from caddsuite.application.trajectory_analytics import _matches_recorded_inputs
from caddsuite.contracts.analysis import TrajectoryAnalysisResult, TrajectoryProcessingResult
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import MDStageResult
from caddsuite.domain.identity import new_ulid


def test_processed_analysis_matches_original_md_files_only_through_exact_parent_chain() -> None:
    def artifact(role: str, letter: str) -> ArtifactRef:
        return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=letter * 64)

    raw_gro, raw_xtc, tpr = (
        artifact("md_gro", "a"),
        artifact("md_xtc", "b"),
        artifact("md_tpr", "c"),
    )
    processed, reference, receipt = (
        artifact("processed", "d"),
        artifact("reference", "e"),
        artifact("receipt", "f"),
    )
    engine = SoftwareRef(name="Fixture only", version="1", kind="engine")
    adapter = SoftwareRef(name="Fixture only", version="1", kind="adapter")
    md = MDStageResult(
        id=new_ulid(),
        system_id=new_ulid(),
        stage_input_id=new_ulid(),
        stage_index=0,
        stage_kind="production",
        engine=engine,
        adapter=adapter,
        parameters={},
        runtime_seconds=1,
        artifacts={"gro": raw_gro, "xtc": raw_xtc, "tpr": tpr},
    )
    parent = TrajectoryProcessingResult(
        id=new_ulid(),
        request_id=new_ulid(),
        simulation_id=md.id,
        processor=engine,
        adapter_id="fixture",
        adapter_version="1",
        parameters={},
        transforms=("make_molecules_whole",),
        reference_structure=reference,
        source_artifacts={"topology": tpr, "segment": raw_xtc},
        output_artifacts={"processed": processed, "reference_structure": reference},
        n_atoms=3,
        n_frames=2,
        frame_interval_ps=1,
        time_range_ps=(0, 1),
    )
    result = TrajectoryAnalysisResult(
        id=new_ulid(),
        request_id=new_ulid(),
        simulation_id=md.id,
        trajectory_id=new_ulid(),
        preprocessing_result_id=parent.id,
        analyzer=engine,
        parameters={},
        source_artifacts={"topology": reference, "trajectory": processed},
        raw_result=receipt,
        metrics=(),
    )
    assert _matches_recorded_inputs(result, "a" * 64, "b" * 64, [md, parent])
    assert not _matches_recorded_inputs(result, "a" * 64, "b" * 64, [parent])
    assert not _matches_recorded_inputs(result, "a" * 64, "0" * 64, [md, parent])
    assert not _matches_recorded_inputs(
        result, "a" * 64, "b" * 64, [md, parent.model_copy(update={"simulation_id": new_ulid()})]
    )
    assert not _matches_recorded_inputs(
        result.model_copy(
            update={"source_artifacts": {"topology": reference, "trajectory": raw_xtc}}
        ),
        "a" * 64,
        "b" * 64,
        [md, parent],
    )
