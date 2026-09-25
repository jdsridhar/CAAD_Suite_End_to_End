"""Strict, hash-linked contracts for engine-neutral trajectory transformations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from caddsuite.contracts.analysis import (
    TrajectoryAnalysisRequest,
    TrajectoryMetric,
    TrajectoryProcessingRequest,
    TrajectoryProcessingResult,
    TrajectorySegmentInput,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import AtomSelection
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid


def artifact(role: str, digest: str = "a" * 64) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest)


def request(**changes: object) -> TrajectoryProcessingRequest:
    values: dict[str, object] = {
        "id": new_ulid(),
        "simulation_id": new_ulid(),
        "topology": artifact("gromacs_tpr", "b" * 64),
        "topology_format": "GROMACS TPR",
        "topology_has_connectivity": True,
        "trajectory_format": "XTC",
        "expected_atom_count": 49_682,
        "segments": (
            TrajectorySegmentInput(
                artifact=artifact("trajectory_segment_1", "c" * 64),
                output_start_time_ps=0,
                n_frames=11,
                frame_interval_ps=100,
            ),
            TrajectorySegmentInput(
                artifact=artifact("trajectory_segment_2", "d" * 64),
                output_start_time_ps=1000,
                n_frames=11,
                frame_interval_ps=100,
            ),
        ),
        "transforms": (
            TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
            TrajectoryTransform.MAKE_MOLECULES_WHOLE,
        ),
    }
    values.update(changes)
    return TrajectoryProcessingRequest.model_validate(values)


def test_processing_request_captures_hashes_and_explicit_segment_time_origins():
    value = request()
    assert value.segments[1].output_start_time_ps == 1000
    assert value.segments[0].output_end_time_ps == 1000
    assert value.transforms == (
        TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
        TrajectoryTransform.MAKE_MOLECULES_WHOLE,
    )


def test_pbc_request_requires_connectivity_bearing_topology():
    with pytest.raises(ValidationError, match="connectivity-bearing topology"):
        request(topology_has_connectivity=False)


def test_processing_request_rejects_duplicate_segments_and_nonmonotonic_origins():
    value = request()
    with pytest.raises(ValidationError, match="unique"):
        request(segments=(value.segments[0], value.segments[0]))
    with pytest.raises(ValidationError, match="strictly increasing"):
        request(segments=(value.segments[1], value.segments[0]))


def test_processing_request_requires_hashed_topology_and_segments():
    value = request()
    with pytest.raises(ValidationError, match="SHA-256"):
        request(topology=ArtifactRef(artifact_id=new_ulid(), role="tpr"))
    with pytest.raises(ValidationError, match="SHA-256"):
        TrajectorySegmentInput(
            artifact=ArtifactRef(artifact_id=new_ulid(), role="xtc"),
            output_start_time_ps=0,
            n_frames=1,
            frame_interval_ps=100,
        )
    assert value.expected_atom_count == 49_682


def test_alignment_requires_verified_fit_and_full_system_output_selections():
    value = request()
    with pytest.raises(ValidationError, match="fit and output selections"):
        request(transforms=(TrajectoryTransform.ALIGN_ROT_TRANS,))
    aligned = TrajectoryProcessingRequest(
        **{
            **value.model_dump(),
            "transforms": [TrajectoryTransform.ALIGN_ROT_TRANS],
            "fit_selection": AtomSelection(description="Protein", n_atoms=1836, verified=True),
            "output_selection": AtomSelection(description="System", n_atoms=49_682, verified=True),
        }
    )
    assert aligned.fit_selection is not None
    assert aligned.fit_selection.n_atoms == 1836
    with pytest.raises(ValidationError, match="complete MD system"):
        request(
            transforms=(TrajectoryTransform.ALIGN_ROT_TRANS,),
            fit_selection=AtomSelection(description="Protein", n_atoms=1836, verified=True),
            output_selection=AtomSelection(description="Protein", n_atoms=1836, verified=True),
        )


def test_normalized_result_requires_hashed_outputs_and_ordered_times():
    value = request()
    software = SoftwareRef(
        name="GROMACS",
        version="2026.3",
        kind=SoftwareKind.ENGINE,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )
    result = TrajectoryProcessingResult(
        id=new_ulid(),
        request_id=value.id,
        simulation_id=value.simulation_id,
        processor=software,
        adapter_id="caddsuite.trajectory.gromacs",
        adapter_version="0.1.0",
        parameters={"pbc_group": "System"},
        transforms=value.transforms,
        source_artifacts={"topology": value.topology, "segment_1": value.segments[0].artifact},
        output_artifacts={"processed": artifact("processed", "e" * 64)},
        n_atoms=49_682,
        n_frames=11,
        frame_interval_ps=100,
        time_range_ps=(0, 1000),
    )
    assert result.n_frames == 11
    with pytest.raises(ValidationError, match="ends before"):
        TrajectoryProcessingResult(**{**result.model_dump(), "time_range_ps": (1000, 0)})
    with pytest.raises(ValidationError, match="SHA-256"):
        TrajectoryProcessingResult(
            **{
                **result.model_dump(),
                "output_artifacts": {
                    "processed": ArtifactRef(artifact_id=new_ulid(), role="processed")
                },
            }
        )


def test_radius_of_gyration_requires_explicit_mass_table():
    with pytest.raises(ValidationError, match="explicit atom-mass table"):
        TrajectoryAnalysisRequest(
            id=new_ulid(),
            simulation_id=new_ulid(),
            trajectory_id=new_ulid(),
            preprocessing_result_id=new_ulid(),
            trajectory=artifact("processed_trajectory"),
            topology=artifact("coordinate_topology"),
            trajectory_format="XTC",
            topology_format="GRO",
            expected_atom_count=3,
            expected_frame_count=11,
            frame_interval_ps=100,
            selections={"protein": AtomSelection(description="protein", n_atoms=3, verified=True)},
            metrics=(TrajectoryMetric.PROTEIN_RADIUS_OF_GYRATION,),
            end_time_ns=1.0,
        )


def test_mass_weighted_rmsd_requires_explicit_mass_table():
    with pytest.raises(ValidationError, match="mass-weighted RMSD"):
        TrajectoryAnalysisRequest(
            id=new_ulid(),
            simulation_id=new_ulid(),
            trajectory_id=new_ulid(),
            preprocessing_result_id=new_ulid(),
            trajectory=artifact("processed_trajectory"),
            topology=artifact("coordinate_topology"),
            trajectory_format="XTC",
            topology_format="GRO",
            expected_atom_count=4,
            expected_frame_count=11,
            frame_interval_ps=100,
            selections={
                "ligand": AtomSelection(description="resname LIG", n_atoms=4, verified=True)
            },
            metrics=(TrajectoryMetric.LIGAND_INTERNAL_RMSD,),
            rmsd_weighting="mass",
            end_time_ns=1.0,
        )
