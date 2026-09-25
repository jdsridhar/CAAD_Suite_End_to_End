"""Strict parsing and cross-checks for gmx_MMPBSA report pairs."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from caddsuite.adapters.binding_energy.gmx_mmpbsa_results import (
    GmxMMPBSAParseError,
    parse_gmx_mmpbsa_results,
)
from caddsuite.contracts.analysis import BindingEnergyMethod

_VALUES = {
    "Complex": ("complex", (10.0, 12.0), "TOTAL", (11.00, 1.00, 1.00, 0.71, 0.71)),
    "Receptor": ("receptor", (4.0, 5.0), "TOTAL", (4.50, 0.50, 0.50, 0.35, 0.35)),
    "Ligand": ("ligand", (1.0, 1.5), "TOTAL", (1.25, 0.25, 0.25, 0.18, 0.18)),
    "Delta (Complex - Receptor - Ligand)": (
        "delta",
        (5.0, 5.5),
        "ΔTOTAL",
        (5.25, 0.25, 0.25, 0.18, 0.18),
    ),
}


def _report_pair() -> tuple[str, str]:
    dat = [
        "|gmx_MMPBSA Version=1.6.3 based on MMPBSA.py v.16.0",
        '|Receptor mask: ":1-4"',
        '|Ligand mask: ":5"',
        "|Calculations performed using 2 complex frames",
        "|Using temperature = 310.00 K",
        "|All units are reported in kcal/mol",
        "GENERALIZED BORN:",
    ]
    csv = ["GENERALIZED BORN:"]
    for label, (_, samples, component, stats) in _VALUES.items():
        dat.extend(
            (
                f"{label}:",
                "Energy Component       Average     SD(Prop.)         SD   SEM(Prop.)        SEM",
                f"{component:16s} {stats[0]:13.2f} {stats[1]:13.2f} {stats[2]:10.2f} "
                f"{stats[3]:12.2f} {stats[4]:10.2f}",
                "-------------------------------------------------------------------------------",
            )
        )
        csv.extend(
            (
                f"{label.split()[0]} Energy Terms",
                "Frame #,TOTAL",
                f"1,{samples[0]}",
                f"2,{samples[1]}",
                "",
            )
        )
    return "\n".join(dat) + "\n", "\n".join(csv) + "\n"


def test_parser_retains_native_tables_metadata_and_propagated_statistics():
    dat, csv = _report_pair()
    result = parse_gmx_mmpbsa_results(dat, csv)

    assert result.method is BindingEnergyMethod.MM_GBSA
    assert result.software_version == "1.6.3"
    assert result.mmpbsa_py_version == "16.0"
    assert result.frame_count == 2
    assert result.temperature_K == 310.0
    assert result.units == "kcal/mol"
    assert result.receptor_mask == ":1-4"
    assert result.ligand_mask == ":5"
    assert result.delta_total.average == 5.25
    assert result.frame_tables["delta"].frame_numbers == (1, 2)
    assert result.frame_tables["delta"].values_for("TOTAL") == (5.0, 5.5)
    assert result.summaries["delta"]["ΔTOTAL"].sd_propagated == 0.25


def test_parser_rejects_summary_frame_disagreement():
    dat, csv = _report_pair()
    altered = dat.replace("ΔTOTAL               5.25", "ΔTOTAL             -99.00")
    if altered == dat:
        altered = dat.replace("ΔTOTAL", "ΔTOTAL")
        altered = altered.replace("5.25", "-99.00", 1)
    with pytest.raises(GmxMMPBSAParseError, match="disagrees with text summary"):
        parse_gmx_mmpbsa_results(altered, csv)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda text: text.replace("2,5.5", "1,5.5"), "strictly increasing"),
        (lambda text: text.replace("2,5.5", "2,nan"), "invalid numeric"),
        (lambda text: text.replace("GENERALIZED BORN:", "", 1), "solvation-method"),
    ],
)
def test_parser_rejects_malformed_frame_tables(mutation: Callable[[str], str], message: str):
    dat, csv = _report_pair()
    with pytest.raises(GmxMMPBSAParseError, match=message):
        parse_gmx_mmpbsa_results(dat, mutation(csv))


@pytest.mark.parametrize(
    ("dat_mutation", "csv_mutation", "message"),
    [
        (lambda text: text.replace("310.00 K", "0 K"), lambda text: text, "temperature"),
        (lambda text: text.replace("kcal/mol", "kJ/mol"), lambda text: text, "energy unit"),
        (
            lambda text: text,
            lambda text: text.replace("Receptor Energy Terms", "Protein Terms"),
            "unexpected row",
        ),
    ],
)
def test_parser_rejects_missing_or_incompatible_metadata(
    dat_mutation: Callable[[str], str],
    csv_mutation: Callable[[str], str],
    message: str,
):
    dat, csv = _report_pair()
    with pytest.raises(GmxMMPBSAParseError, match=message):
        parse_gmx_mmpbsa_results(dat_mutation(dat), csv_mutation(csv))


def test_frame_table_values_are_immutable_sequences():
    dat, csv = _report_pair()
    result = parse_gmx_mmpbsa_results(dat, csv)
    values = result.frame_tables["complex"].values_for("TOTAL")
    assert values == (10.0, 12.0)
    assert isinstance(values, tuple)


@pytest.mark.legacy_data
def test_legacy_parser_reads_all_four_archived_projects_and_preserves_inputs():
    data_root = os.environ.get("CADDSUITE_MDSUITE_DATA")
    if not data_root:
        pytest.skip("set CADDSUITE_MDSUITE_DATA for the read-only four-project regression")
    root = Path(data_root) / "projects"
    expected = {
        "2M2D_LIG": (-4.37, ":1-118", ":119"),
        "2M2D_STD": (-1.16, ":1-118", ":119"),
        "5NIU_LIG": (-34.76, ":1-251", ":252"),
        "5NIU_STD": (-45.94, ":1-251", ":252"),
    }

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    for project, (mean_delta, receptor_mask, ligand_mask) in expected.items():
        analysis = root / project / "gromacs" / "analysis"
        dat_path = analysis / "FINAL_RESULTS_MMGBSA.dat"
        csv_path = analysis / "FINAL_RESULTS_MMGBSA.csv"
        before = (digest(dat_path), digest(csv_path))
        result = parse_gmx_mmpbsa_results(
            dat_path.read_text(encoding="utf-8"), csv_path.read_text(encoding="utf-8")
        )
        assert result.method is BindingEnergyMethod.MM_GBSA
        assert result.software_version == "v1.6.3"
        assert result.frame_count == 1001
        assert result.temperature_K == 310.0
        assert result.receptor_mask == receptor_mask
        assert result.ligand_mask == ligand_mask
        assert result.frame_tables["complex"].frame_numbers == tuple(range(1, 1002))
        assert result.delta_total.average == pytest.approx(mean_delta, abs=0.005)
        assert len(result.frame_tables) == 4
        assert (digest(dat_path), digest(csv_path)) == before
