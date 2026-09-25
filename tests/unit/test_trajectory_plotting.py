from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from caddsuite.adapters.visualization.matplotlib_trajectory import (
    MatplotlibTrajectoryPlotter,
    TrajectoryPlotError,
    _crop_trace,
    _effective_window,
    _Trace,
)
from caddsuite.contracts.analysis import MetricDefinition, MetricSeries
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.visualization import TrajectoryPlotRequest, TrajectoryPlotSource
from caddsuite.domain.identity import new_ulid


def _metric(path: Path, name: str = "rg_protein", *, axis: str = "time_ns") -> MetricSeries:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return MetricSeries(
        name=name,
        definition=MetricDefinition(target_selection="protein"),
        unit="Å",
        axis=axis,  # type: ignore[arg-type]
        value_column="value",
        series=ArtifactRef(artifact_id=new_ulid(), role=name, sha256=digest),
        window_ns=(0.0, 10.0),
    )


def _source(
    path: Path, label: str, *, name: str = "rg_protein", axis: str = "time_ns"
) -> TrajectoryPlotSource:
    return TrajectoryPlotSource(
        analysis_id=new_ulid(),
        trajectory_id=new_ulid(),
        label=label,
        metric=_metric(path, name, axis=axis),
    )


def _write_csv(path: Path, contents: str) -> Path:
    path.write_text(contents, encoding="utf-8")
    return path


def test_metric_csv_shape_is_upcast_for_legacy_rmsf_and_sasa() -> None:
    old_rmsf = MetricSeries.model_validate(
        {
            "name": "rmsf_ca",
            "definition": {"target_selection": "protein and name CA"},
            "unit": "Å",
            "series": {"artifact_id": new_ulid(), "role": "rmsf"},
            "summary": {},
            "window_ns": [0, 1],
        }
    )
    old_sasa = MetricSeries.model_validate(
        {
            "name": "sasa",
            "definition": {"target_selection": "protein"},
            "unit": "Å²",
            "series": {"artifact_id": new_ulid(), "role": "sasa"},
            "summary": {},
            "window_ns": [0, 1],
        }
    )
    assert (old_rmsf.axis, old_rmsf.value_column) == ("residue", "rmsf_A")
    assert (old_sasa.axis, old_sasa.value_column) == ("time_ns", "sasa_A2")


def test_plot_contract_rejects_incompatible_comparison_definitions(tmp_path: Path) -> None:
    left = _write_csv(tmp_path / "left.csv", "time_ns,value\n0,1\n1,2\n")
    right = _write_csv(tmp_path / "right.csv", "time_ns,value\n0,1\n1,2\n")
    source1 = _source(left, "run A")
    source2 = _source(right, "run B")
    source2 = source2.model_copy(
        update={
            "metric": source2.metric.model_copy(
                update={"definition": MetricDefinition(target_selection="backbone")}
            )
        }
    )
    with pytest.raises(ValidationError, match="matching measurement definitions"):
        TrajectoryPlotRequest(
            id=new_ulid(),
            sources=(source1, source2),
            comparison_basis="same target and selection protocol",
        )


def test_comparison_requires_explicit_basis_and_compatible_units(tmp_path: Path) -> None:
    first = _write_csv(tmp_path / "first.csv", "time_ns,value\n0,1\n1,2\n")
    second = _write_csv(tmp_path / "second.csv", "time_ns,value\n0,1\n1,2\n")
    with pytest.raises(ValidationError, match="scientifically comparable"):
        TrajectoryPlotRequest(id=new_ulid(), sources=(_source(first, "A"), _source(second, "B")))


def test_renderer_verifies_hash_and_emits_both_highlight_variants(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    series = _write_csv(tmp_path / "metric.csv", "time_ns,value\n0,1.2\n1,1.3\n2,1.4\n")
    source = _source(series, "replicate 1")
    request = TrajectoryPlotRequest(
        id=new_ulid(),
        sources=(source,),
        highlight_window_ns=(0.5, 1.5),
        highlight_label="Equilibration review interval",
    )
    rendered = MatplotlibTrajectoryPlotter().render(
        request,
        series_paths={source.metric.series.artifact_id: series},
        output_directory=tmp_path / "plots",
    )
    assert [plot.variant for plot in rendered] == ["plain", "highlighted"]
    assert all(plot.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for plot in rendered)
    assert all(
        plot.sha256 == hashlib.sha256(plot.path.read_bytes()).hexdigest() for plot in rendered
    )
    assert all(plot.effective_window_ns == (0.0, 2.0) for plot in rendered)
    assert all(plot.request.id == request.id for plot in rendered)
    assert not list((tmp_path / "plots").glob(".plot-*.png"))


def test_renderer_rejects_tampered_metric_artifact(tmp_path: Path) -> None:
    series = _write_csv(tmp_path / "metric.csv", "time_ns,value\n0,1.2\n1,1.3\n")
    source = _source(series, "run")
    series.write_text("time_ns,value\n0,99\n1,1.3\n", encoding="utf-8")
    request = TrajectoryPlotRequest(id=new_ulid(), sources=(source,))
    with pytest.raises(TrajectoryPlotError, match="hash does not match") as error:
        MatplotlibTrajectoryPlotter().render(
            request,
            series_paths={source.metric.series.artifact_id: series},
            output_directory=tmp_path / "plots",
        )
    assert error.value.code == "VISUALIZATION.INPUT_HASH_MISMATCH"


def test_comparison_uses_actual_samples_and_common_time_extent(tmp_path: Path) -> None:
    first = _Trace((0.0, 1.0, 2.0), (2.0, 3.0, 4.0))
    second = _Trace((0.5, 1.5, 2.5), (5.0, 6.0, 7.0))
    request = TrajectoryPlotRequest(
        id=new_ulid(),
        sources=(
            TrajectoryPlotSource(
                analysis_id=new_ulid(),
                trajectory_id=new_ulid(),
                label="A",
                metric=MetricSeries(
                    name="rg_protein",
                    definition=MetricDefinition(target_selection="protein"),
                    unit="Å",
                    axis="time_ns",
                    value_column="value",
                    series=ArtifactRef(artifact_id=new_ulid(), role="A", sha256="a" * 64),
                    window_ns=(0, 3),
                ),
            ),
            TrajectoryPlotSource(
                analysis_id=new_ulid(),
                trajectory_id=new_ulid(),
                label="B",
                metric=MetricSeries(
                    name="rg_protein",
                    definition=MetricDefinition(target_selection="protein"),
                    unit="Å",
                    axis="time_ns",
                    value_column="value",
                    series=ArtifactRef(artifact_id=new_ulid(), role="B", sha256="b" * 64),
                    window_ns=(0, 3),
                ),
            ),
        ),
        comparison_basis="same protein and atom-selection definition",
    )
    window = _effective_window(request, [first, second], "time_ns")
    assert window == (0.5, 2.0)
    assert _crop_trace(first, "time_ns", window, "rg_protein") == _Trace((1.0, 2.0), (3.0, 4.0))
    assert _crop_trace(second, "time_ns", window, "rg_protein") == _Trace((0.5, 1.5), (5.0, 6.0))


def test_explicit_comparison_window_must_stay_in_shared_time_range(tmp_path: Path) -> None:
    left = _write_csv(tmp_path / "left.csv", "time_ns,value\n0,1\n1,2\n2,3\n")
    right = _write_csv(tmp_path / "right.csv", "time_ns,value\n1,4\n2,5\n3,6\n")
    request = TrajectoryPlotRequest(
        id=new_ulid(),
        sources=(_source(left, "A"), _source(right, "B")),
        display_window_ns=(0.0, 1.5),
        comparison_basis="same target and measurement definitions",
    )
    with pytest.raises(TrajectoryPlotError, match="shared time range") as error:
        _effective_window(
            request,
            [
                _Trace((0.0, 1.0, 2.0), (1.0, 2.0, 3.0)),
                _Trace((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)),
            ],
            "time_ns",
        )
    assert error.value.code == "VISUALIZATION.DISPLAY_WINDOW_OUTSIDE_COMMON_RANGE"


def test_renderer_accepts_residue_csv_and_rejects_highlight_window(tmp_path: Path) -> None:
    rmsf = _write_csv(
        tmp_path / "rmsf.csv", "residue,value,resname,atom\n10,0.2,GLY,CA\n11,0.3,ALA,CA\n"
    )
    source = _source(rmsf, "run", name="rmsf_ca", axis="residue")
    with pytest.raises(ValidationError, match="residue-axis"):
        TrajectoryPlotRequest(id=new_ulid(), sources=(source,), highlight_window_ns=(0, 1))
    pytest.importorskip("matplotlib")
    request = TrajectoryPlotRequest(id=new_ulid(), sources=(source,))
    rendered = MatplotlibTrajectoryPlotter().render(
        request,
        series_paths={source.metric.series.artifact_id: rmsf},
        output_directory=tmp_path / "plots",
    )
    assert len(rendered) == 1
    assert rendered[0].effective_window_ns is None
