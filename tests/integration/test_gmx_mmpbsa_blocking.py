"""Read-only block-statistics regression on archived gmx_MMPBSA CSVs."""

from __future__ import annotations

import hashlib
import os
from itertools import pairwise
from pathlib import Path

import pytest

from caddsuite.adapters.binding_energy.gmx_mmpbsa_results import parse_gmx_mmpbsa_results
from caddsuite.analysis.blocking import block_estimates

DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
pytestmark = [
    pytest.mark.legacy_data,
    pytest.mark.skipif(not DATA_ROOT, reason="set CADDSUITE_MDSUITE_DATA for archived reports"),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_archived_binding_energy_series_exposes_block_size_sensitivity_read_only():
    assert DATA_ROOT is not None
    root = Path(DATA_ROOT) / "projects"
    projects = ("2M2D_LIG", "2M2D_STD", "5NIU_LIG", "5NIU_STD")

    for name in projects:
        analysis = root / name / "gromacs/analysis"
        dat = analysis / "FINAL_RESULTS_MMGBSA.dat"
        csv = analysis / "FINAL_RESULTS_MMGBSA.csv"
        before = (_sha256(dat), _sha256(csv))
        parsed = parse_gmx_mmpbsa_results(
            dat.read_text(encoding="utf-8"),
            csv.read_text(encoding="utf-8"),
        )
        values = parsed.frame_tables["delta"].values_for("TOTAL")
        estimates = block_estimates(values)
        after = (_sha256(dat), _sha256(csv))

        assert len(values) == 1001
        assert tuple(item.block_size_frames for item in estimates) == (1, 2, 4, 8, 16, 32, 64, 128)
        assert all(later.sem_block > earlier.sem_block for earlier, later in pairwise(estimates))
        assert all(
            later.n_effective < earlier.n_effective for earlier, later in pairwise(estimates)
        )
        assert before == after
