"""Workflow-stage adapter for normalized pose-to-complex coordinate assembly."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import TypeVar

from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.docking import DockingResult, Pose
from caddsuite.contracts.registry import Compound, CompoundForm
from caddsuite.contracts.structure import PreparedReceptor, Structure
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.structure.complex_builder import (
    ComplexBuildError,
    ComplexBuildPolicy,
    assemble_complex_pdb,
)
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation

T = TypeVar("T", bound=VersionedContract)


class CoordinateComplexBuilderHandler:
    """Assemble a transparent PDB derivative and return its typed lineage contract."""

    adapter_id = "structure.complex_builder"
    adapter_version = "1.0.0"
    engine_version = "caddsuite-coordinate-assembly/1.0.0"

    def __init__(self, *, artifact_store: ArtifactStore, sessions: sessionmaker[Session]) -> None:
        self.artifact_store = artifact_store
        self.sessions = sessions

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, Compound):
            return str(value.id)
        if isinstance(value, CompoundForm):
            return str(value.compound_id)
        if isinstance(value, Pose):
            return str(value.id)
        raise TypeError(f"complex-builder fan-out cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        receptor = self._input(inputs, "receptor", PreparedReceptor)
        docking = self._input(inputs, "docking", DockingResult)
        pose = self._input(inputs, "pose", Pose)
        compound = self._input(inputs, "compound", Compound)
        form = self._input(inputs, "form", CompoundForm)
        structure = self._input(inputs, "target_structure", Structure)
        receptor_ref = receptor.artifacts.get("prepared_structure_pdb")
        if receptor_ref is None or receptor_ref.sha256 is None or pose.structure.sha256 is None:
            raise ValueError(
                "complex assembly requires hashed receptor PDB and normalized pose SDF"
            )
        return {
            "prepared_receptor_pdb": receptor_ref.sha256,
            "normalized_pose_sdf": pose.structure.sha256,
            "lineage_contracts": hashlib.sha256(
                "\n".join(
                    value.model_dump_json()
                    for value in (compound, form, structure, receptor, docking, pose)
                ).encode()
            ).hexdigest(),
        }

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        docking = self._input(inputs, "docking", DockingResult)
        pose = self._input(inputs, "pose", Pose)
        return (
            {
                "docking.pose_rank": pose.rank,
                "docking.pose_score_kcal_mol": pose.score.value,
                "docking.site_method": str(docking.run.params.get("site_method", "unknown")),
            },
            frozenset(
                {
                    "docking.pose_rank",
                    "docking.pose_score_kcal_mol",
                    "docking.site_method",
                }
            ),
        )

    def execute(self, invocation: TaskInvocation) -> Complex:
        compound = self._input(invocation.inputs, "compound", Compound)
        form = self._input(invocation.inputs, "form", CompoundForm)
        structure = self._input(invocation.inputs, "target_structure", Structure)
        receptor = self._input(invocation.inputs, "receptor", PreparedReceptor)
        docking = self._input(invocation.inputs, "docking", DockingResult)
        pose = self._input(invocation.inputs, "pose", Pose)
        receptor_ref = receptor.artifacts.get("prepared_structure_pdb")
        if receptor_ref is None or receptor_ref.sha256 is None or pose.structure.sha256 is None:
            raise StageExecutionFailure(
                "STRUCTURE.COMPLEX_INPUT_ARTIFACT_MISSING",
                "Complex assembly requires hashed receptor PDB and normalized pose SDF artifacts.",
            )
        for label, digest in (
            ("prepared receptor PDB", receptor_ref.sha256),
            ("normalized pose SDF", pose.structure.sha256),
        ):
            if not self.artifact_store.verify(digest):
                raise StageExecutionFailure(
                    "STRUCTURE.COMPLEX_INPUT_ARTIFACT_INVALID",
                    f"{label} is missing from storage or its SHA-256 does not match.",
                )
        try:
            policy = ComplexBuildPolicy.model_validate(invocation.task.params)
            assembly = assemble_complex_pdb(
                prepared_receptor_pdb=self.artifact_store.path_for(
                    receptor_ref.sha256
                ).read_bytes(),
                pose_sdf=self.artifact_store.path_for(pose.structure.sha256).read_bytes(),
                compound=compound,
                form=form,
                structure=structure,
                receptor=receptor,
                docking=docking,
                pose=pose,
                policy=policy,
            )
        except (ComplexBuildError, OSError, ValueError) as exc:
            raise StageExecutionFailure("STRUCTURE.COMPLEX_ASSEMBLY_FAILED", str(exc)) from exc

        blob = self.artifact_store.put_bytes(assembly.pdb_bytes)
        with self.sessions.begin() as session:
            row = register_blob(
                session,
                blob,
                kind="coordinate_complex_pdb",
                media_type="chemical/x-pdb",
                original_name="complex.pdb",
            )
        return Complex(
            id=new_ulid(),
            compound_id=compound.id,
            form_id=form.id,
            target_id=structure.target_id,
            structure_id=structure.id,
            prepared_receptor_id=receptor.id,
            docking_run_id=docking.run.id,
            pose_id=pose.id,
            protein=receptor_ref.model_copy(update={"role": "complex_protein_input"}),
            ligand=pose.structure.model_copy(update={"role": "complex_ligand_input_sdf"}),
            assembled=ArtifactRef(
                artifact_id=row.id,
                role="coordinate_complex_pdb",
                sha256=blob.sha256,
            ),
            protein_atom_count=assembly.protein_atom_count,
            ligand_atom_count=assembly.ligand_atom_count,
            ligand_heavy_atom_count=assembly.ligand_heavy_atom_count,
            coordinate_fidelity_max_dev_A=assembly.coordinate_fidelity_max_dev_A,
            parameters={
                **policy.model_dump(mode="json"),
                "ligand_chain_id": assembly.chain_id,
                "ligand_residue_id": assembly.residue_id,
                "receptor_hydrogens": "retained",
                "receptor_heterogens": "retained as present in prepared receptor",
                "force_field_parameterized": False,
                "md_ready": False,
            },
        )

    @staticmethod
    def _input(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, kind: type[T]) -> T:
        values = inputs.get(name, ())
        if len(values) != 1 or not isinstance(values[0], kind):
            raise StageExecutionFailure(
                "STRUCTURE.COMPLEX_INPUT_CONTRACT_INVALID",
                f"Input port {name!r} requires exactly one {kind.__name__} contract.",
            )
        return values[0]
