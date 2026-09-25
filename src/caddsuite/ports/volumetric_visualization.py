"""Port for rendering normalized volumetric fields into reviewable figures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from caddsuite.contracts.base import ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.contracts.visualization import (
    FrontierOrbitalRenderRequest,
    FukuiRenderRequest,
    MEPRenderRequest,
)

VolumetricRenderRequest = FrontierOrbitalRenderRequest | MEPRenderRequest | FukuiRenderRequest


class VolumetricRenderCapabilities(ContractModel):
    """Render formats and request families implemented by a visualization adapter."""

    formats: tuple[NonEmptyStr, ...] = ("png",)
    request_kinds: tuple[NonEmptyStr, ...] = ("frontier_orbitals", "mep", "fukui")


@dataclass(frozen=True, slots=True)
class RenderedVolumetricFigure:
    """Local rendering receipt; application service ingests the file as an artifact."""

    path: Path
    sha256: str
    renderer: SoftwareRef
    adapter_id: str
    adapter_version: str
    request: VolumetricRenderRequest
    input_artifact_ids: tuple[str, ...]
    input_hashes: tuple[str, ...]
    warnings: tuple[str, ...]


class VolumetricVisualizationEngine(Protocol):
    """Renderer plugin consumes cube artifact files without knowing their QM producer."""

    adapter_id: NonEmptyStr
    version: NonEmptyStr
    capabilities: VolumetricRenderCapabilities

    def render(
        self,
        request: VolumetricRenderRequest,
        *,
        cube_paths: dict[str, Path],
        output_directory: Path,
    ) -> RenderedVolumetricFigure: ...
