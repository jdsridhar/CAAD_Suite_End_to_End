"""Engine-neutral plotting requests for already-normalized scientific results."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from caddsuite.contracts.analysis import MetricSeries
from caddsuite.contracts.base import (
    ArtifactRef,
    ContractModel,
    NonEmptyStr,
    NonNegativeFloat,
    PositiveFloat,
    VersionedContract,
)
from caddsuite.domain.identity import ULIDStr


class TrajectoryPlotSource(ContractModel):
    """One normalized metric trace and its stable source analysis identity."""

    analysis_id: ULIDStr
    trajectory_id: ULIDStr
    label: NonEmptyStr
    metric: MetricSeries


class TrajectoryPlotRequest(VersionedContract):
    """Render a metric from one run or compare compatible runs without resampling."""

    schema_version: str = "trajectory_plot_request/1.0"

    id: ULIDStr
    sources: Annotated[tuple[TrajectoryPlotSource, ...], Field(min_length=1)]
    display_window_ns: tuple[NonNegativeFloat, NonNegativeFloat] | None = None
    highlight_window_ns: tuple[NonNegativeFloat, NonNegativeFloat] | None = None
    highlight_label: NonEmptyStr = "Highlighted interval"
    comparison_basis: NonEmptyStr | None = None
    title: NonEmptyStr | None = None
    width_inches: Annotated[float, Field(gt=0, le=30)] = 8.5
    height_inches: Annotated[float, Field(gt=0, le=30)] = 4.5
    dpi: Annotated[int, Field(ge=72, le=600)] = 200

    @model_validator(mode="after")
    def _compatible_sources_and_windows(self) -> TrajectoryPlotRequest:
        if len({source.analysis_id for source in self.sources}) != len(self.sources):
            raise ValueError("a plot request must not repeat an analysis result")
        if len({source.label for source in self.sources}) != len(self.sources):
            raise ValueError("plot trace labels must be unique")
        first = self.sources[0].metric
        if first.series.sha256 is None:
            raise ValueError("every plotted metric artifact must include a SHA-256 hash")
        for source in self.sources[1:]:
            metric = source.metric
            if metric.series.sha256 is None:
                raise ValueError("every plotted metric artifact must include a SHA-256 hash")
            if (metric.name, metric.unit, metric.axis) != (first.name, first.unit, first.axis):
                raise ValueError("compared traces must use the same metric, axis, and unit")
            if (
                metric.definition.target_selection,
                metric.definition.fit_selection,
                metric.definition.refit,
                metric.definition.weighting,
            ) != (
                first.definition.target_selection,
                first.definition.fit_selection,
                first.definition.refit,
                first.definition.weighting,
            ):
                raise ValueError("compared traces must have matching measurement definitions")
        if len(self.sources) > 1 and self.comparison_basis is None:
            raise ValueError("comparisons must record why these runs are scientifically comparable")
        for name, window in (
            ("display_window_ns", self.display_window_ns),
            ("highlight_window_ns", self.highlight_window_ns),
        ):
            if window is not None and window[1] <= window[0]:
                raise ValueError(f"{name} must have positive duration")
        if first.axis != "time_ns" and (
            self.display_window_ns is not None or self.highlight_window_ns is not None
        ):
            raise ValueError("time windows cannot be applied to a residue-axis metric")
        if (
            self.display_window_ns is not None
            and self.highlight_window_ns is not None
            and max(self.display_window_ns[0], self.highlight_window_ns[0])
            >= min(self.display_window_ns[1], self.highlight_window_ns[1])
        ):
            raise ValueError("highlighted interval must overlap the displayed time window")
        return self


PixelSize = tuple[Annotated[int, Field(ge=200, le=6000)], Annotated[int, Field(ge=200, le=6000)]]


class CubeRenderInput(ContractModel):
    """One hash-addressed cube artifact and the selected scalar field within it."""

    artifact: ArtifactRef
    dataset_index: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def _hashed_source(self) -> CubeRenderInput:
        if self.artifact.sha256 is None:
            raise ValueError("render input cube artifact must include a SHA-256 hash")
        return self


class FrontierOrbitalRenderRequest(VersionedContract):
    """Render signed HOMO/LUMO wavefunction isosurfaces on a shared molecular frame."""

    schema_version: str = "frontier_orbital_render_request/1.0"

    id: ULIDStr
    homo: CubeRenderInput
    lumo: CubeRenderInput
    isovalue_au: PositiveFloat = 0.02
    homo_energy_eV: float | None = None
    lumo_energy_eV: float | None = None
    size_pixels: PixelSize = (1400, 700)
    show_molecular_skeleton: bool = True

    @model_validator(mode="after")
    def _distinct_inputs(self) -> FrontierOrbitalRenderRequest:
        if self.homo.artifact.artifact_id == self.lumo.artifact.artifact_id:
            raise ValueError("HOMO and LUMO must reference distinct cube artifacts")
        return self


class MEPRenderRequest(VersionedContract):
    """Color a total-density isosurface using ESP values from a compatible grid."""

    schema_version: str = "mep_render_request/1.0"

    id: ULIDStr
    density: CubeRenderInput
    esp: CubeRenderInput
    density_isovalue_e_bohr3: PositiveFloat = 0.001
    esp_clip_au: tuple[float, float] = (-0.05, 0.05)
    colormap: NonEmptyStr = "RdBu"
    size_pixels: PixelSize = (900, 900)
    show_molecular_skeleton: bool = False

    @model_validator(mode="after")
    def _valid_inputs_and_clip(self) -> MEPRenderRequest:
        if self.density.artifact.artifact_id == self.esp.artifact.artifact_id:
            raise ValueError("density and ESP must reference distinct cube artifacts")
        low, high = self.esp_clip_au
        if not math.isfinite(low) or not math.isfinite(high) or high <= low:
            raise ValueError("ESP display range must be finite and increasing")
        return self


class FukuiRenderRequest(VersionedContract):
    """Render a finite-difference Fukui density field on its positive isosurface."""

    schema_version: str = "fukui_render_request/1.0"

    id: ULIDStr
    neutral_density: CubeRenderInput
    charged_density: CubeRenderInput
    sign: Literal["plus", "minus"]
    isovalue_e_bohr3: PositiveFloat = 0.003
    size_pixels: PixelSize = (700, 700)
    show_molecular_skeleton: bool = True

    @model_validator(mode="after")
    def _distinct_inputs(self) -> FukuiRenderRequest:
        if self.neutral_density.artifact.artifact_id == self.charged_density.artifact.artifact_id:
            raise ValueError("neutral and charged densities must reference distinct cube artifacts")
        return self
