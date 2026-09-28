"""Workflow stage for seeded RDKit ETKDG embedding through the existing chemistry function."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import cast

from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.chem.embed import EmbeddingPolicy, embed_conformer
from caddsuite.chem.standardize import _rdkit
from caddsuite.contracts.base import ArtifactRef, SoftwareRef, VersionedContract
from caddsuite.contracts.registry import CompoundForm, Conformer
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.attempt_context import record_generated_artifact
from caddsuite.storage.artifacts import register_blob
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler, TaskInvocation


class RDKitEmbeddingStageHandler:
    adapter_id = "chemistry.rdkit_etkdg"
    adapter_version = "0.1.0"

    def __init__(self, stage: StageDefinition, services: LocalRuntimeServices) -> None:
        raw = stage.params.get("policy")
        if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
            raise ValueError("conformer embedding requires an explicit policy object with a seed")
        self.policy = EmbeddingPolicy.model_validate(dict(raw))
        self.services = services
        self.engine_version = str(_rdkit()[1].rdkitVersion)
        self.software = SoftwareRef(
            name="RDKit",
            version=self.engine_version,
            kind=SoftwareKind.LIBRARY,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        )

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, CompoundForm):
            return str(value.id if scope == "compound_form" else value.compound_id)
        raise TypeError(f"conformer embedding cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        forms = inputs.get("form", ())
        return {
            f"form[{index}]": hashlib.sha256(value.model_dump_json().encode()).hexdigest()
            for index, value in enumerate(forms)
            if isinstance(value, CompoundForm)
        }

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> Conformer:
        values = invocation.inputs.get("form", ())
        if len(values) != 1 or not isinstance(values[0], CompoundForm):
            raise ValueError("conformer embedding requires exactly one CompoundForm input")

        def register_sdf(data: bytes, role: str) -> ArtifactRef:
            blob = self.services.artifacts.put_bytes(data)
            with self.services.sessions.begin() as session:
                row = register_blob(
                    session,
                    blob,
                    kind="ligand_conformer",
                    media_type="chemical/x-mdl-sdfile",
                    original_name=f"{new_ulid()}.sdf",
                )
                ref = ArtifactRef(
                    artifact_id=row.id,
                    role=role,
                    sha256=row.sha256,
                )
            record_generated_artifact(ref, role)
            return ref

        result = embed_conformer(values[0], policy=self.policy, register_artifact=register_sdf)
        return result.conformer


class RDKitEmbeddingStagePlugin:
    plugin_id = "caddsuite.stage_handlers.rdkit_embedding"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="chemistry.embed",
            engine="rdkit_etkdg",
            inputs=(CapabilityInput(name="form", contracts=(CompoundForm.schema_id(),)),),
            outputs=(Conformer.schema_id(),),
            for_each=("compound", "compound_form"),
            iteration_contracts={
                "compound": (CompoundForm.schema_id(),),
                "compound_form": (CompoundForm.schema_id(),),
            },
            fanout_anchor={"compound_form": "form"},
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        return cast(StageHandler, RDKitEmbeddingStageHandler(stage, services))


def plugin_factory() -> RDKitEmbeddingStagePlugin:
    return RDKitEmbeddingStagePlugin()
