"""Engine-independent block-averaging diagnostics for correlated time series.

Block size is deliberately supplied by the workflow/user when a single SEM is to be
reported. Candidate powers of two are diagnostics, not an automatic plateau decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import fsum, isfinite, sqrt
from statistics import mean, variance


@dataclass(frozen=True, slots=True)
class BlockEstimate:
    block_size_frames: int
    n_blocks: int
    frames_used: int
    frames_dropped: int
    block_mean: float
    block_sd: float
    sem_block: float
    n_effective: float | None


def block_estimates(
    values: Sequence[float],
    *,
    minimum_blocks: int = 4,
    selected_block_size: int | None = None,
) -> tuple[BlockEstimate, ...]:
    """Compute non-overlapping block-mean SEM candidates in input time order.

    The sample standard deviation (ddof=1) of equal-sized block means is divided by
    sqrt(number of blocks). Any trailing incomplete block is excluded and reported.
    Effective sample size is sample variance of the retained frame values divided by
    the block-mean SEM squared, bounded to [1, frames_used]. No plateau is inferred.
    """
    if minimum_blocks < 2:
        raise ValueError("minimum_blocks must be at least 2")
    if len(values) < 1:
        raise ValueError("time series must not be empty")
    series = tuple(float(value) for value in values)
    if any(not isfinite(value) for value in series):
        raise ValueError("time series values must be finite")
    if selected_block_size is not None and selected_block_size < 1:
        raise ValueError("selected block size must be positive")

    sizes = {1}
    size = 2
    while len(series) // size >= minimum_blocks:
        sizes.add(size)
        size *= 2
    if selected_block_size is not None:
        if len(series) // selected_block_size < minimum_blocks:
            raise ValueError("selected block size leaves fewer than minimum_blocks complete blocks")
        sizes.add(selected_block_size)

    estimates: list[BlockEstimate] = []
    for block_size in sorted(sizes):
        n_blocks = len(series) // block_size
        if n_blocks < minimum_blocks:
            continue
        frames_used = n_blocks * block_size
        truncated = series[:frames_used]
        block_means = tuple(
            mean(truncated[start : start + block_size])
            for start in range(0, frames_used, block_size)
        )
        block_mean = mean(block_means)
        block_sd = sqrt(fsum((value - block_mean) ** 2 for value in block_means) / (n_blocks - 1))
        sem = block_sd / sqrt(n_blocks)
        if sem == 0.0:
            n_effective = float(frames_used) if variance(truncated) == 0.0 else None
        else:
            n_effective = min(
                float(frames_used),
                max(1.0, variance(truncated) / (sem * sem)),
            )
        estimates.append(
            BlockEstimate(
                block_size_frames=block_size,
                n_blocks=n_blocks,
                frames_used=frames_used,
                frames_dropped=len(series) - frames_used,
                block_mean=block_mean,
                block_sd=block_sd,
                sem_block=sem,
                n_effective=n_effective,
            )
        )
    return tuple(estimates)
