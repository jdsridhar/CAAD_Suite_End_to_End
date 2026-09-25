"""Correlation-aware block SEM tests with analytically inspectable series."""

from __future__ import annotations

from math import sqrt
from statistics import stdev

import pytest

from caddsuite.analysis.blocking import block_estimates


def test_independent_single_frame_blocks_recover_sample_sem_and_effective_count():
    values = tuple(float(value) for value in range(8))
    result = block_estimates(values, minimum_blocks=4)

    assert [item.block_size_frames for item in result] == [1, 2]
    assert result[0].sem_block == pytest.approx(stdev(values) / sqrt(len(values)))
    assert result[0].n_effective == pytest.approx(8.0)
    assert result[0].frames_used == 8
    assert result[0].frames_dropped == 0


def test_correlated_repeated_pairs_increase_block_sem_and_reduce_effective_count():
    values = tuple(float(value) for value in range(8) for _ in range(2))
    result = block_estimates(values, minimum_blocks=4)
    frame_sem = result[0].sem_block
    pair_blocks = result[1]

    assert pair_blocks.block_size_frames == 2
    assert pair_blocks.sem_block > frame_sem
    assert pair_blocks.n_effective < len(values)
    assert pair_blocks.n_blocks == 8


def test_selected_non_power_of_two_block_records_discarded_tail():
    result = block_estimates(
        tuple(float(value) for value in range(19)),
        minimum_blocks=4,
        selected_block_size=3,
    )
    selected = next(item for item in result if item.block_size_frames == 3)

    assert selected.n_blocks == 6
    assert selected.frames_used == 18
    assert selected.frames_dropped == 1


def test_constant_series_has_zero_sem_without_inventing_zero_effective_samples():
    result = block_estimates((2.0,) * 12, minimum_blocks=4)

    assert result[0].sem_block == 0.0
    assert result[0].n_effective == 12.0


@pytest.mark.parametrize(
    ("values", "options", "message"),
    [
        ((), {}, "must not be empty"),
        ((1.0, float("nan"), 2.0, 3.0), {}, "finite"),
        ((1.0, 2.0, 3.0), {"minimum_blocks": 1}, "at least 2"),
        (
            (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0),
            {"minimum_blocks": 4, "selected_block_size": 2},
            "fewer than minimum_blocks",
        ),
    ],
)
def test_rejects_invalid_series_or_unsupported_block_choice(values, options, message):
    with pytest.raises(ValueError, match=message):
        block_estimates(values, **options)
