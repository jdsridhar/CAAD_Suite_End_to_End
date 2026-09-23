"""Engine-neutral adapter port types shared by plugins and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.validation.issues import ValidationIssue


@dataclass(frozen=True, slots=True)
class AdapterContext:
    inputs: dict[str, VersionedContract]
    parameters: dict[str, object]
    working_directory: Path


@dataclass(frozen=True, slots=True)
class CommandStep:
    """One safe argv invocation requested by an adapter; shell strings are not accepted."""

    argv: tuple[str, ...]
    working_directory: Path
    environment: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    commands: tuple[CommandStep, ...]
    expected_outputs: tuple[str, ...]


class StageAdapter(Protocol):
    """Minimal common adapter contract; scientific-family ports can extend it later."""

    adapter_id: str
    version: str

    def validate_input(self, context: AdapterContext) -> tuple[ValidationIssue, ...]: ...

    def plan(self, context: AdapterContext) -> ExecutionPlan: ...

    def normalize_result(
        self, raw_outputs: dict[str, ArtifactRef], context: AdapterContext
    ) -> VersionedContract: ...
