"""Strict parser for gmx_MMPBSA text summaries and per-frame CSV tables."""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Literal

from caddsuite.contracts.analysis import BindingEnergyMethod

EnergySection = Literal["complex", "receptor", "ligand", "delta"]

_SECTION_LABELS: dict[str, EnergySection] = {
    "Complex": "complex",
    "Receptor": "receptor",
    "Ligand": "ligand",
    "Delta (Complex - Receptor - Ligand)": "delta",
}
_CSV_SECTION_LABELS: dict[str, EnergySection] = {
    "Complex Energy Terms": "complex",
    "Receptor Energy Terms": "receptor",
    "Ligand Energy Terms": "ligand",
    "Delta Energy Terms": "delta",
}
_SUMMARY_HEADER = ("Energy", "Component", "Average", "SD(Prop.)", "SD", "SEM(Prop.)", "SEM")
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?$")
_TOLERANCE_KCAL_PER_MOL = 0.011


class GmxMMPBSAParseError(ValueError):
    """The native gmx_MMPBSA outputs are incomplete, inconsistent, or malformed."""


@dataclass(frozen=True, slots=True)
class ReportedEnergyStatistics:
    average: float
    sd_propagated: float
    sd: float
    sem_propagated: float
    sem: float


@dataclass(frozen=True, slots=True)
class EnergyFrameTable:
    section: EnergySection
    columns: tuple[str, ...]
    frame_numbers: tuple[int, ...]
    values: tuple[tuple[float, ...], ...]

    def values_for(self, column: str) -> tuple[float, ...]:
        """Return one component series by its native CSV heading."""
        try:
            column_index = self.columns.index(column)
        except ValueError as exc:
            raise KeyError(column) from exc
        if column_index == 0:
            raise KeyError("Frame # is metadata, not an energy component")
        return tuple(row[column_index - 1] for row in self.values)


@dataclass(frozen=True, slots=True)
class GmxMMPBSAResults:
    method: BindingEnergyMethod
    software_version: str
    mmpbsa_py_version: str
    frame_count: int
    temperature_K: float
    units: Literal["kcal/mol"]
    receptor_mask: str
    ligand_mask: str
    summaries: dict[EnergySection, dict[str, ReportedEnergyStatistics]]
    frame_tables: dict[EnergySection, EnergyFrameTable]

    @property
    def delta_total(self) -> ReportedEnergyStatistics:
        """The native complex − receptor − ligand total summary."""
        return self.summaries["delta"]["ΔTOTAL"]


def _float(value: str, *, context: str) -> float:
    if not _NUMBER.fullmatch(value):
        raise GmxMMPBSAParseError(f"{context}: invalid numeric value {value!r}")
    try:
        parsed = float(value.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise GmxMMPBSAParseError(f"{context}: invalid numeric value {value!r}") from exc
    if not math.isfinite(parsed):
        raise GmxMMPBSAParseError(f"{context}: non-finite numeric value {value!r}")
    return parsed


def _method(value: str, *, source: str) -> tuple[BindingEnergyMethod, str]:
    normalized = value.strip().removesuffix(":").upper()
    if normalized == "GENERALIZED BORN":
        return BindingEnergyMethod.MM_GBSA, normalized
    if normalized in {"POISSON BOLTZMANN", "POISSON-BOLTZMANN"}:
        return BindingEnergyMethod.MM_PBSA, normalized
    raise GmxMMPBSAParseError(f"{source}: unsupported or missing solvation method {value!r}")


def _metadata(
    text: str,
) -> tuple[str, str, int, float, Literal["kcal/mol"], str, str]:
    version_match = re.search(
        r"gmx_MMPBSA\s+Version=([^\s]+)\s+based on MMPBSA\.py\s+v\.?([^\s]+)",
        text,
    )
    frame_match = re.search(r"Calculations performed using\s+(\d+)\s+complex frames", text)
    temperature_match = re.search(
        r"Using temperature\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)\s*K",
        text,
    )
    units_match = re.search(r"All units are reported in\s+([^\s]+)", text)
    receptor_match = re.search(r'Receptor mask:\s*"([^"]+)"', text)
    ligand_match = re.search(r'Ligand mask:\s*"([^"]+)"', text)
    missing = [
        name
        for name, match in (
            ("software version", version_match),
            ("complex frame count", frame_match),
            ("temperature", temperature_match),
            ("units", units_match),
            ("receptor mask", receptor_match),
            ("ligand mask", ligand_match),
        )
        if match is None
    ]
    if missing:
        raise GmxMMPBSAParseError("text summary is missing metadata: " + ", ".join(missing))
    if (
        version_match is None
        or frame_match is None
        or temperature_match is None
        or units_match is None
        or receptor_match is None
        or ligand_match is None
    ):
        raise GmxMMPBSAParseError("text summary metadata is incomplete")
    if units_match.group(1) != "kcal/mol":
        raise GmxMMPBSAParseError(f"unsupported energy unit {units_match.group(1)!r}")
    frame_count = int(frame_match.group(1))
    if frame_count < 1:
        raise GmxMMPBSAParseError("complex frame count must be positive")
    temp = _float(temperature_match.group(1), context="temperature")
    if temp <= 0:
        raise GmxMMPBSAParseError("temperature must be positive")
    return (
        version_match.group(1),
        version_match.group(2),
        frame_count,
        temp,
        "kcal/mol",
        receptor_match.group(1),
        ligand_match.group(1),
    )


def _summary_line(
    line: str, *, section: EnergySection, line_number: int
) -> tuple[str, tuple[float, ...]] | None:
    tokens = line.split()
    if len(tokens) < 6:
        return None
    tail = tokens[-5:]
    if not all(_NUMBER.fullmatch(token) for token in tail):
        return None
    label = " ".join(tokens[:-5])
    if not label:
        raise GmxMMPBSAParseError(f"text line {line_number}: statistic row has no component name")
    numeric = tuple(_float(token, context=f"text line {line_number} {label}") for token in tail)
    if section == "delta" and not label.startswith("Δ"):
        raise GmxMMPBSAParseError(
            f"text line {line_number}: delta component {label!r} lacks the native Δ prefix"
        )
    return label, numeric


def _parse_summaries(
    text: str,
) -> tuple[BindingEnergyMethod, dict[EnergySection, dict[str, ReportedEnergyStatistics]]]:
    current_method: str | None = None
    current_section: EnergySection | None = None
    in_table = False
    found_headers: set[EnergySection] = set()
    summaries: dict[EnergySection, dict[str, ReportedEnergyStatistics]] = {}

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip().lstrip("|").strip()
        if stripped in {"GENERALIZED BORN:", "POISSON BOLTZMANN:", "POISSON-BOLTZMANN:"}:
            if current_method is not None:
                raise GmxMMPBSAParseError(
                    "text summary contains multiple solvation-method sections"
                )
            current_method = stripped
            current_section = None
            in_table = False
            continue
        if stripped in {f"{label}:" for label in _SECTION_LABELS}:
            label = stripped[:-1]
            current_section = _SECTION_LABELS[label]
            if current_section in summaries:
                raise GmxMMPBSAParseError(f"text summary duplicates the {current_section} section")
            summaries[current_section] = {}
            in_table = False
            continue
        if current_section is None:
            continue
        if stripped.split() == list(_SUMMARY_HEADER):
            if current_section in found_headers:
                raise GmxMMPBSAParseError(
                    f"text summary duplicates the {current_section} table header"
                )
            found_headers.add(current_section)
            in_table = True
            continue
        if not in_table or not stripped or set(stripped) == {"-"}:
            continue
        parsed = _summary_line(stripped, section=current_section, line_number=line_number)
        if parsed is None:
            continue
        label, values = parsed
        if label in summaries[current_section]:
            raise GmxMMPBSAParseError(
                f"text line {line_number}: duplicate {current_section} component {label!r}"
            )
        summaries[current_section][label] = ReportedEnergyStatistics(*values)

    if current_method is None:
        raise GmxMMPBSAParseError("text summary has no recognized solvation-method heading")
    method, _ = _method(current_method, source="text summary")
    required_sections = set(_SECTION_LABELS.values())
    if set(summaries) != required_sections or found_headers != required_sections:
        raise GmxMMPBSAParseError(
            "text summary must contain exactly Complex, Receptor, Ligand, and Delta tables"
        )
    for section, section_summaries in summaries.items():
        total_name = "ΔTOTAL" if section == "delta" else "TOTAL"
        if total_name not in section_summaries:
            raise GmxMMPBSAParseError(f"text summary {section} table lacks its TOTAL component")
        if not section_summaries:
            raise GmxMMPBSAParseError(f"text summary {section} table is empty")
    return method, summaries


def _parse_frame_tables(
    text: str,
) -> tuple[BindingEnergyMethod, dict[EnergySection, EnergyFrameTable]]:
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise GmxMMPBSAParseError(f"CSV output is malformed: {exc}") from exc

    current_method: str | None = None
    current_section: EnergySection | None = None
    current_columns: tuple[str, ...] | None = None
    table_columns: dict[EnergySection, tuple[str, ...]] = {}
    table_frames: dict[EnergySection, list[int]] = {}
    table_values: dict[EnergySection, list[tuple[float, ...]]] = {}

    for row_number, row in enumerate(rows, start=1):
        cells = [cell.strip() for cell in row]
        if not cells or not any(cells):
            continue
        first = cells[0]
        if first in {"GENERALIZED BORN:", "POISSON BOLTZMANN:", "POISSON-BOLTZMANN:"}:
            if current_method is not None:
                raise GmxMMPBSAParseError("CSV output contains multiple solvation-method sections")
            current_method = first
            continue
        if first in _CSV_SECTION_LABELS:
            section = _CSV_SECTION_LABELS[first]
            if section in table_frames:
                raise GmxMMPBSAParseError(f"CSV output duplicates the {section} energy table")
            current_section = section
            current_columns = None
            table_frames[section] = []
            table_values[section] = []
            continue
        if current_section is None:
            raise GmxMMPBSAParseError(
                f"CSV line {row_number}: unexpected content outside an energy table"
            )
        if first == "Frame #":
            if current_columns is not None:
                raise GmxMMPBSAParseError(
                    f"CSV line {row_number}: duplicate header in {current_section}"
                )
            if len(set(cells)) != len(cells) or len(cells) < 2:
                raise GmxMMPBSAParseError(
                    f"CSV line {row_number}: energy columns are missing or repeated"
                )
            current_columns = tuple(cells)
            table_columns[current_section] = current_columns
            continue
        if set(first) == {"-"}:
            continue
        if not first.isdigit():
            raise GmxMMPBSAParseError(
                f"CSV line {row_number}: unexpected row {first!r} in {current_section} table"
            )
        if current_columns is None:
            raise GmxMMPBSAParseError(
                f"CSV line {row_number}: data precedes the energy-column header"
            )
        if len(cells) != len(current_columns):
            raise GmxMMPBSAParseError(
                f"CSV line {row_number}: expected {len(current_columns)} fields, found {len(cells)}"
            )
        frame = int(first)
        if frame < 1:
            raise GmxMMPBSAParseError(f"CSV line {row_number}: frame numbers must be positive")
        prior = table_frames[current_section]
        if prior and frame <= prior[-1]:
            raise GmxMMPBSAParseError(f"CSV line {row_number}: frames must be strictly increasing")
        values = tuple(
            _float(cell, context=f"CSV line {row_number}, column {current_columns[index + 1]}")
            for index, cell in enumerate(cells[1:])
        )
        prior.append(frame)
        table_values[current_section].append(values)

    if current_method is None:
        raise GmxMMPBSAParseError("CSV output has no recognized solvation-method heading")
    method, _ = _method(current_method, source="CSV output")
    required_sections = set(_SECTION_LABELS.values())
    if set(table_frames) != required_sections or set(table_columns) != required_sections:
        raise GmxMMPBSAParseError(
            "CSV output must contain exactly Complex, Receptor, Ligand, and Delta tables"
        )
    columns = table_columns["complex"]
    if columns[0] != "Frame #" or "TOTAL" not in columns[1:]:
        raise GmxMMPBSAParseError("CSV energy tables must have Frame # and TOTAL columns")
    if any(table_columns[section] != columns for section in required_sections):
        raise GmxMMPBSAParseError("CSV energy-table columns differ between sections")
    reference_frames = table_frames["complex"]
    if not reference_frames:
        raise GmxMMPBSAParseError("CSV complex table has no frame data")
    for section in required_sections:
        if not table_frames[section]:
            raise GmxMMPBSAParseError(f"CSV {section} table has no frame data")
        if table_frames[section] != reference_frames:
            raise GmxMMPBSAParseError("CSV energy tables do not contain the same frame sequence")

    result = {
        section: EnergyFrameTable(
            section=section,
            columns=table_columns[section],
            frame_numbers=tuple(table_frames[section]),
            values=tuple(table_values[section]),
        )
        for section in required_sections
    }
    return method, result


def _check_summary_matches_frames(
    summaries: dict[EnergySection, dict[str, ReportedEnergyStatistics]],
    tables: dict[EnergySection, EnergyFrameTable],
) -> None:
    for section, table in tables.items():
        summary_names = set(summaries[section])
        if section == "delta":
            summary_names = {name.removeprefix("Δ") for name in summary_names}
        if summary_names != set(table.columns[1:]):
            raise GmxMMPBSAParseError(
                f"{section} text-summary components do not match the CSV columns"
            )
        for column in table.columns[1:]:
            summary_name = f"Δ{column}" if section == "delta" else column
            reported = summaries[section][summary_name]
            samples = table.values_for(column)
            computed_mean = mean(samples)
            if abs(computed_mean - reported.average) > _TOLERANCE_KCAL_PER_MOL:
                raise GmxMMPBSAParseError(
                    f"{section} {column} CSV mean disagrees with text summary: "
                    f"{computed_mean:.6f} vs {reported.average:.6f} kcal/mol"
                )
            if samples:
                computed_sd = pstdev(samples)
                computed_sem = computed_sd / math.sqrt(len(samples))
                if abs(computed_sd - reported.sd) > _TOLERANCE_KCAL_PER_MOL:
                    raise GmxMMPBSAParseError(
                        f"{section} {column} CSV sample SD disagrees with text summary"
                    )
                if abs(computed_sem - reported.sem) > _TOLERANCE_KCAL_PER_MOL:
                    raise GmxMMPBSAParseError(
                        f"{section} {column} CSV sample SEM disagrees with text summary"
                    )


def parse_gmx_mmpbsa_results(dat_text: str, csv_text: str) -> GmxMMPBSAResults:
    """Parse and cross-check native text and CSV outputs without changing either source.

    Text-report values are printed to two decimals, so reported means, population SDs, and
    population SD/√N values are compared with unrounded CSV statistics using a 0.011 kcal/mol
    tolerance. gmx_MMPBSA 1.6.3 computes these columns with NumPy's default ``ddof=0`` even
    though its report text calls them sample SD/SEM. The propagated SD/SEM columns are
    preserved as reported and are not reinterpreted as correlation-aware trajectory uncertainty.
    """
    if not dat_text.strip() or not csv_text.strip():
        raise GmxMMPBSAParseError("both non-empty text and CSV outputs are required")
    metadata = _metadata(dat_text)
    text_method, summaries = _parse_summaries(dat_text)
    csv_method, tables = _parse_frame_tables(csv_text)
    if text_method is not csv_method:
        raise GmxMMPBSAParseError("text and CSV outputs report different solvation methods")
    version, base_version, frame_count, temperature, units, receptor_mask, ligand_mask = metadata
    if len(tables["complex"].frame_numbers) != frame_count:
        raise GmxMMPBSAParseError(
            "CSV frame count differs from the text summary's declared complex-frame count"
        )
    _check_summary_matches_frames(summaries, tables)
    return GmxMMPBSAResults(
        method=text_method,
        software_version=version,
        mmpbsa_py_version=base_version,
        frame_count=frame_count,
        temperature_K=temperature,
        units=units,
        receptor_mask=receptor_mask,
        ligand_mask=ligand_mask,
        summaries=summaries,
        frame_tables=tables,
    )
