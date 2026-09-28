"""Engine-neutral blind whole-protein box stage with explicit chain selection."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import TypeVar, cast

from caddsuite.application.handlers import StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import VersionedContract
from caddsuite.contracts.structure import (
    BindingSite,
    PreparedReceptor,
    Structure,
)
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.structure.binding_site import BindingSitePolicy, blind_protein_site
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageHandler, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class BlindProteinSiteStageHandler:
    adapter_id = "structure.binding_site.blind_protein_box"
    adapter_version = "1.0.0"
    engine_version = "caddsuite-geometry/1.0.0"

    def __init__(self, stage: StageDefinition, services: LocalRuntimeServices) -> None:
        selected = stage.params.get("selected_chain_ids")
        if (
            not isinstance(selected, (list, tuple))
            or not selected
            or any(not isinstance(item, str) or not item for item in selected)
        ):
            raise ValueError(
                "blind protein binding-site stage requires explicit selected_chain_ids"
            )
        if len(set(selected)) != len(selected):
            raise ValueError("selected_chain_ids must be unique")
        self.selected_chain_ids = tuple(selected)
        raw_policy = stage.params.get("policy", {})
        if not isinstance(raw_policy, Mapping) or not all(
            isinstance(key, str) for key in raw_policy
        ):
            raise ValueError("binding-site policy must be an object")
        self.policy = BindingSitePolicy.model_validate(dict(raw_policy))
        self.artifacts: ArtifactStore = services.artifacts

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, Structure):
            return str(value.id)
        if isinstance(value, PreparedReceptor):
            return str(value.structure_id)
        raise TypeError(f"binding-site stage cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        structure = _one(inputs, "structure", Structure)
        receptor = _one(inputs, "receptor", PreparedReceptor)
        source = receptor.artifacts.get("prepared_structure")
        if source is None or source.sha256 is None:
            raise ValueError("prepared receptor lacks its normalized mmCIF artifact")
        return {
            "source_structure": structure.raw.sha256 or "",
            "prepared_receptor": source.sha256,
            "contracts": hashlib.sha256(
                (structure.model_dump_json() + receptor.model_dump_json()).encode()
            ).hexdigest(),
        }

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> BindingSite:
        structure = _one(invocation.inputs, "structure", Structure)
        receptor = _one(invocation.inputs, "receptor", PreparedReceptor)
        if receptor.structure_id != structure.id:
            raise ValueError("prepared receptor does not derive from the supplied Structure")
        artifact = receptor.artifacts.get("prepared_structure")
        if (
            artifact is None
            or artifact.sha256 is None
            or not self.artifacts.verify(artifact.sha256)
        ):
            raise ValueError("prepared receptor mmCIF artifact is missing or has an invalid digest")
        mmcif = self.artifacts.path_for(artifact.sha256).read_bytes()
        if hashlib.sha256(mmcif).hexdigest() != artifact.sha256:
            raise ValueError("prepared receptor mmCIF artifact failed SHA-256 verification")
        return blind_protein_site(
            structure.target_id,
            artifact,
            mmcif,
            selected_chain_ids=self.selected_chain_ids,
            policy=self.policy,
        )


def _one(
    inputs: Mapping[str, tuple[VersionedContract, ...]],
    port: str,
    expected: type[C],
) -> C:
    values = inputs.get(port, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise ValueError(f"binding-site port {port!r} requires exactly one {expected.__name__}")
    return values[0]


class BindingSiteStagePlugin:
    plugin_id = "caddsuite.stage_handlers.binding_site"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="structure.binding_site",
            engine="blind_protein_box",
            inputs=(
                CapabilityInput(name="structure", contracts=(Structure.schema_id(),)),
                CapabilityInput(name="receptor", contracts=(PreparedReceptor.schema_id(),)),
            ),
            outputs=(BindingSite.schema_id(),),
            for_each=("target",),
            iteration_contracts={"target": (Structure.schema_id(), PreparedReceptor.schema_id())},
        )
        return (StageHandlerRegistration(capability, self._build),)

    @staticmethod
    def _build(stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        return cast(StageHandler, BlindProteinSiteStageHandler(stage, services))


def plugin_factory() -> BindingSiteStagePlugin:
    return BindingSiteStagePlugin()
