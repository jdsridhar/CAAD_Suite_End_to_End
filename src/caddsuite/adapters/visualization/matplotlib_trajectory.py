"""Matplotlib renderer for hash-verified, normalized trajectory metric CSV artifacts."""

from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from caddsuite.contracts.base import SoftwareRef
from caddsuite.contracts.visualization import TrajectoryPlotRequest
from caddsuite.domain.enums import SoftwareKind
from caddsuite.ports.trajectory_plotting import (
    RenderedTrajectoryPlot,
    TrajectoryPlottingCapabilities,
)

_BLUE = "#2a78d6"
_AQUA = "#1baf7a"
_ORANGE = "#eb6834"
_MUTED = "#898781"
_GRID = "#e1e0d9"
_INK = "#0b0b0b"
_BACKGROUND = "#fcfcfb"
_PALETTE = (_BLUE, _AQUA, _ORANGE)
_TITLES = {
    "rmsd_backbone": "Protein backbone RMSD",
    "rmsd_ligand_pose": "Ligand pose RMSD",
    "rmsd_ligand_internal": "Ligand internal RMSD",
    "rmsf_ca": "Per-residue Cα RMSF",
    "rg_protein": "Protein radius of gyration",
    "sasa": "Solvent-accessible surface area",
    "mindist_protein_ligand": "Protein-ligand minimum distance",
    "contacts_protein_ligand": "Protein-ligand atom-pair contacts",
}


class TrajectoryPlotError(ValueError):
    """Actionable plot input or optional-renderer error with a stable error code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class _Trace:
    x: tuple[float, ...]
    y: tuple[float, ...]


class MatplotlibTrajectoryPlotter:
    """Render normalized metric artifacts without recomputing any scientific metric.

    The adapter verifies content hashes before reading CSV files. Comparison traces keep their
    original samples: this renderer never interpolates or resamples one trajectory onto another.
    """

    adapter_id = "caddsuite.visualization.matplotlib.trajectory"
    version = "0.1.0"
    capabilities = TrajectoryPlottingCapabilities()

    def render(
        self,
        request: TrajectoryPlotRequest,
        *,
        series_paths: dict[str, Path],
        output_directory: Path,
    ) -> tuple[RenderedTrajectoryPlot, ...]:
        traces: list[_Trace] = []
        for source in request.sources:
            artifact = source.metric.series
            path = series_paths.get(artifact.artifact_id)
            if path is None:
                raise TrajectoryPlotError(
                    "VISUALIZATION.INPUT_ARTIFACT_MISSING",
                    f"No staged file was supplied for metric artifact {artifact.artifact_id}.",
                )
            expected_hash = artifact.sha256
            if expected_hash is None:
                raise TrajectoryPlotError(
                    "VISUALIZATION.INPUT_HASH_MISSING",
                    f"Metric artifact {artifact.artifact_id} has no SHA-256 hash.",
                )
            if _sha256(path) != expected_hash:
                raise TrajectoryPlotError(
                    "VISUALIZATION.INPUT_HASH_MISMATCH",
                    f"Metric CSV hash does not match artifact {artifact.artifact_id}.",
                )
            traces.append(
                _read_trace(
                    path,
                    source.metric.axis,
                    source.metric.value_column,
                    artifact.artifact_id,
                    source.metric.window_ns,
                )
            )

        axis = request.sources[0].metric.axis
        effective_window = _effective_window(request, traces, axis)
        selected_traces = tuple(
            _crop_trace(trace, axis, effective_window, request.sources[index].metric.name)
            for index, trace in enumerate(traces)
        )
        if axis == "residue" and any(trace.x != traces[0].x for trace in traces[1:]):
            raise TrajectoryPlotError(
                "VISUALIZATION.RESIDUE_MAPPING_MISMATCH",
                "Per-residue traces use different residue coordinates; "
                "overlay would misalign residues.",
            )

        if request.highlight_window_ns is not None:
            start, end = request.highlight_window_ns
            if effective_window is None or max(start, effective_window[0]) >= min(
                end, effective_window[1]
            ):
                raise TrajectoryPlotError(
                    "VISUALIZATION.HIGHLIGHT_OUTSIDE_DATA",
                    "The highlighted interval does not overlap the plotted trajectory samples.",
                )

        try:
            import matplotlib
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from matplotlib.figure import Figure
        except ImportError as exc:  # optional visualization dependency
            raise TrajectoryPlotError(
                "VISUALIZATION.DEPENDENCY_MISSING",
                "Matplotlib is required for PNG output; install caddsuite[visualization].",
            ) from exc

        try:
            matplotlib_version = str(matplotlib.__version__)
            outputs: list[RenderedTrajectoryPlot] = []
            variants = ("plain", "highlighted") if request.highlight_window_ns else ("plain",)
            output_directory.mkdir(parents=True, exist_ok=True)
            metric_name = request.sources[0].metric.name
            slug = re.sub(r"[^A-Za-z0-9_-]+", "_", metric_name).strip("_") or "metric"
            software = SoftwareRef(
                name="Matplotlib",
                version=matplotlib_version,
                kind=SoftwareKind.LIBRARY,
            )
            for variant in variants:
                highlighted = variant == "highlighted"
                path = output_directory / f"plot-{request.id}-{slug}-{variant}.png"
                if path.exists():
                    raise TrajectoryPlotError(
                        "VISUALIZATION.OUTPUT_ALREADY_EXISTS",
                        f"Refusing to overwrite an existing plot: {path.name}.",
                    )
                with tempfile.NamedTemporaryFile(
                    dir=output_directory, prefix=".plot-", suffix=".png", delete=False
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                try:
                    with matplotlib.rc_context(
                        {
                            "font.family": "sans-serif",
                            "font.sans-serif": ["DejaVu Sans", "Arial", "sans-serif"],
                            "axes.edgecolor": _MUTED,
                            "axes.labelcolor": _INK,
                            "text.color": _INK,
                            "xtick.color": _MUTED,
                            "ytick.color": _MUTED,
                            "figure.facecolor": _BACKGROUND,
                            "axes.facecolor": _BACKGROUND,
                            "savefig.facecolor": _BACKGROUND,
                            "text.usetex": False,
                        }
                    ):
                        figure = Figure(
                            figsize=(request.width_inches, request.height_inches), dpi=request.dpi
                        )
                        FigureCanvasAgg(figure)
                        axis_plot = figure.add_subplot(1, 1, 1)
                        metric = request.sources[0].metric
                        title = request.title or _TITLES.get(
                            metric_name, metric_name.replace("_", " ")
                        )
                        axis_plot.set_title(f"{title} — {metric.unit}", loc="left", fontsize=10)
                        for index, (source, trace) in enumerate(
                            zip(request.sources, selected_traces, strict=True)
                        ):
                            color = _PALETTE[index % len(_PALETTE)]
                            axis_plot.plot(
                                trace.x,
                                trace.y,
                                color=color,
                                linewidth=1.35,
                                label=source.label,
                                marker="." if len(trace.x) == 1 else None,
                                markersize=5,
                            )
                        axis_plot.set_xlabel("Time (ns)" if metric.axis == "time_ns" else "Residue")
                        axis_plot.set_ylabel(metric.unit)
                        axis_plot.spines["top"].set_visible(False)
                        axis_plot.spines["right"].set_visible(False)
                        axis_plot.spines["left"].set_color(_MUTED)
                        axis_plot.spines["bottom"].set_color(_MUTED)
                        axis_plot.grid(axis="y", color=_GRID, linewidth=0.8, zorder=0)
                        axis_plot.set_axisbelow(True)
                        if metric.name == "contacts_protein_ligand":
                            axis_plot.set_ylim(bottom=0)
                        if highlighted and request.highlight_window_ns is not None:
                            start, end = request.highlight_window_ns
                            axis_plot.axvspan(start, end, color=_ORANGE, alpha=0.12, zorder=0)
                            axis_plot.axvline(start, color=_ORANGE, linewidth=1.1, linestyle="--")
                            axis_plot.axvline(end, color=_ORANGE, linewidth=1.1, linestyle="--")
                            axis_plot.plot(
                                [],
                                [],
                                color=_ORANGE,
                                linewidth=5,
                                alpha=0.28,
                                label=f"{request.highlight_label} ({start:g}–{end:g} ns)",
                            )
                        axis_plot.legend(frameon=False, loc="best", fontsize=8)
                        if effective_window is not None:
                            axis_plot.set_xlim(*effective_window)
                        figure.tight_layout()
                        figure.savefig(temporary_path, format="png", dpi=request.dpi)
                        figure.clear()
                    try:
                        os.link(temporary_path, path)
                    except FileExistsError as exc:
                        raise TrajectoryPlotError(
                            "VISUALIZATION.OUTPUT_ALREADY_EXISTS",
                            f"Refusing to overwrite an existing plot: {path.name}.",
                        ) from exc
                finally:
                    temporary_path.unlink(missing_ok=True)
                outputs.append(
                    RenderedTrajectoryPlot(
                        path=path,
                        sha256=_sha256(path),
                        metric_name=metric_name,
                        variant=variant,  # type: ignore[arg-type]
                        renderer=software,
                        adapter_id=self.adapter_id,
                        adapter_version=self.version,
                        request=request,
                        analysis_ids=tuple(str(source.analysis_id) for source in request.sources),
                        source_hashes=tuple(
                            source.metric.series.sha256 or "" for source in request.sources
                        ),
                        effective_window_ns=effective_window,
                    )
                )
            return tuple(outputs)
        except TrajectoryPlotError:
            raise
        except OSError as exc:
            raise TrajectoryPlotError(
                "VISUALIZATION.OUTPUT_WRITE_FAILED",
                f"Could not write plot output in {output_directory}: {exc}",
                retryable=True,
            ) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise TrajectoryPlotError(
            "VISUALIZATION.INPUT_READ_FAILED", f"Could not read artifact {path}: {exc}"
        ) from exc
    return digest.hexdigest()


def _read_trace(
    path: Path,
    axis: str,
    value_column: str,
    artifact_id: str,
    declared_window_ns: tuple[float, float],
) -> _Trace:
    x_values: list[float] = []
    y_values: list[float] = []
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            expected_axis = "time_ns" if axis == "time_ns" else "residue"
            if (
                reader.fieldnames is None
                or len(reader.fieldnames) != len(set(reader.fieldnames))
                or expected_axis not in reader.fieldnames
                or value_column not in reader.fieldnames
                or expected_axis == value_column
            ):
                raise TrajectoryPlotError(
                    "VISUALIZATION.CSV_SCHEMA_INVALID",
                    f"Metric artifact {artifact_id} must contain distinct {expected_axis} and "
                    f"{value_column} columns.",
                )
            for line_number, row in enumerate(reader, start=2):
                try:
                    x = float(row[expected_axis] or "")
                    y = float(row[value_column] or "")
                except (TypeError, ValueError) as exc:
                    raise TrajectoryPlotError(
                        "VISUALIZATION.CSV_VALUE_INVALID",
                        f"Artifact {artifact_id} has a non-numeric value at line {line_number}.",
                    ) from exc
                if not math.isfinite(x) or not math.isfinite(y):
                    raise TrajectoryPlotError(
                        "VISUALIZATION.CSV_VALUE_INVALID",
                        f"Artifact {artifact_id} has a non-finite value at line {line_number}.",
                    )
                if x_values and (x < x_values[-1] if axis == "residue" else x <= x_values[-1]):
                    raise TrajectoryPlotError(
                        "VISUALIZATION.CSV_ORDER_INVALID",
                        f"Artifact {artifact_id} has unordered {expected_axis} values.",
                    )
                if axis == "time_ns" and not (
                    declared_window_ns[0] - 1e-9 <= x <= declared_window_ns[1] + 1e-9
                ):
                    raise TrajectoryPlotError(
                        "VISUALIZATION.TIME_OUTSIDE_DECLARED_WINDOW",
                        f"Artifact {artifact_id} contains a time outside its declared "
                        "metric window.",
                    )
                x_values.append(x)
                y_values.append(y)
    except OSError as exc:
        raise TrajectoryPlotError(
            "VISUALIZATION.INPUT_READ_FAILED", f"Could not read metric artifact {path}: {exc}"
        ) from exc
    if not x_values:
        raise TrajectoryPlotError(
            "VISUALIZATION.CSV_EMPTY", f"Metric artifact {artifact_id} contains no data rows."
        )
    return _Trace(tuple(x_values), tuple(y_values))


def _effective_window(
    request: TrajectoryPlotRequest, traces: list[_Trace], axis: str
) -> tuple[float, float] | None:
    if axis == "residue":
        return None
    start = max(trace.x[0] for trace in traces) if len(traces) > 1 else traces[0].x[0]
    end = min(trace.x[-1] for trace in traces) if len(traces) > 1 else traces[0].x[-1]
    if end < start:
        raise TrajectoryPlotError(
            "VISUALIZATION.NO_COMMON_TIME_RANGE",
            "Compared metric artifacts have no overlapping time range.",
        )
    if request.display_window_ns is not None:
        requested_start, requested_end = request.display_window_ns
        if requested_start < start or requested_end > end:
            raise TrajectoryPlotError(
                "VISUALIZATION.DISPLAY_WINDOW_OUTSIDE_COMMON_RANGE",
                "The displayed interval must fit within every compared run's shared time range.",
            )
        return request.display_window_ns
    return (start, end)


def _crop_trace(
    trace: _Trace,
    axis: str,
    window: tuple[float, float] | None,
    metric_name: str,
) -> _Trace:
    if axis == "residue" or window is None:
        return trace
    selected = tuple(
        (x, y) for x, y in zip(trace.x, trace.y, strict=True) if window[0] <= x <= window[1]
    )
    if not selected:
        raise TrajectoryPlotError(
            "VISUALIZATION.WINDOW_HAS_NO_SAMPLES",
            f"The requested window contains no samples for {metric_name}.",
        )
    return _Trace(tuple(item[0] for item in selected), tuple(item[1] for item in selected))
