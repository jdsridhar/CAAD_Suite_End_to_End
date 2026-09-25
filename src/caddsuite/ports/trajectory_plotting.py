"""Port for rendering normalized trajectory metrics into reviewable figures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from caddsuite.contracts.base import ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.contracts.visualization import TrajectoryPlotRequest


class TrajectoryPlottingCapabilities(ContractModel):
    """Renderer formats and normalized metric axes supported by an implementation."""

    formats: tuple[Literal["png"], ...] = ("png",)
    axes: tuple[Literal["time_ns", "residue"], ...] = ("time_ns", "residue")


@dataclass(frozen=True)
class RenderedTrajectoryPlot:
    """Local render receipt; the application layer ingests the file as an artifact."""

    path: Path
    sha256: str
    metric_name: str
    variant: Literal["plain", "highlighted"]
    renderer: SoftwareRef
    adapter_id: str
    adapter_version: str
    request: TrajectoryPlotRequest
    analysis_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    effective_window_ns: tuple[float, float] | None


class TrajectoryPlottingEngine(Protocol):
    """Renderer plugin; it consumes contract CSVs and knows no trajectory engine."""

    adapter_id: NonEmptyStr
    version: NonEmptyStr
    capabilities: TrajectoryPlottingCapabilities

    def render(
        self,
        request: TrajectoryPlotRequest,
        *,
        series_paths: dict[str, Path],
        output_directory: Path,
    ) -> tuple[RenderedTrajectoryPlot, ...]: ...
