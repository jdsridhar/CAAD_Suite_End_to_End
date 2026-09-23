"""Typed stage capabilities consumed by the workflow compiler.

Capabilities describe normalized ports and supported iteration scopes. They contain no
executable paths or engine commands; installation discovery and execution stay in adapters
and executors.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field, model_validator

from caddsuite.contracts.base import ContractModel, NonEmptyStr
from caddsuite.workflow.definition import ForEach


class CapabilityInput(ContractModel):
    """A named input port and the exact normalized contracts it accepts."""

    name: NonEmptyStr
    contracts: tuple[NonEmptyStr, ...] = Field(min_length=1)
    required: bool = True

    @model_validator(mode="after")
    def contracts_are_unique(self) -> CapabilityInput:
        if len(self.contracts) != len(set(self.contracts)):
            raise ValueError(f"input port {self.name!r} repeats a contract")
        return self


class StageCapability(ContractModel):
    """Static contract for one stage kind and optional engine implementation."""

    kind: NonEmptyStr
    engine: NonEmptyStr | None = None
    inputs: tuple[CapabilityInput, ...] = ()
    outputs: tuple[NonEmptyStr, ...] = ()
    for_each: tuple[ForEach, ...] = ()
    iteration_contracts: dict[ForEach, tuple[NonEmptyStr, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def capability_is_consistent(self) -> StageCapability:
        input_names = [port.name for port in self.inputs]
        if len(input_names) != len(set(input_names)):
            raise ValueError(f"capability {self.kind!r} repeats an input port")
        if len(self.outputs) != len(set(self.outputs)):
            raise ValueError(f"capability {self.kind!r} repeats an output contract")
        if len(self.for_each) != len(set(self.for_each)):
            raise ValueError(f"capability {self.kind!r} repeats a fan-out scope")
        if set(self.iteration_contracts) - set(self.for_each):
            raise ValueError("iteration contracts declare an unsupported fan-out scope")
        accepted_inputs = {contract for port in self.inputs for contract in port.contracts}
        for scope, contracts in self.iteration_contracts.items():
            if not contracts or not set(contracts) <= accepted_inputs:
                raise ValueError(
                    f"fan-out scope {scope!r} must name contracts accepted on input ports"
                )
        return self


class CapabilityRegistry:
    """Deterministic lookup by (stage kind, engine); duplicate registrations are rejected."""

    def __init__(self, capabilities: Iterable[StageCapability]) -> None:
        self._by_key: dict[tuple[str, str | None], StageCapability] = {}
        for capability in capabilities:
            key = (capability.kind, capability.engine)
            if key in self._by_key:
                raise ValueError(f"duplicate stage capability registration: {key!r}")
            self._by_key[key] = capability

    def for_kind(self, kind: str) -> tuple[StageCapability, ...]:
        return tuple(
            self._by_key[key]
            for key in sorted(self._by_key, key=lambda item: (item[0], item[1] or ""))
            if key[0] == kind
        )

    def resolve(self, kind: str, engine: str | None) -> StageCapability | None:
        return self._by_key.get((kind, engine))
