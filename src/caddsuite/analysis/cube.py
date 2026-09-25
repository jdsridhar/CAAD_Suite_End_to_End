"""Engine-independent reader for a bounded Gaussian CUBE format subset.

Cube coordinates are normalized to Bohr in memory. NumPy is imported only when a
cube is read, so importing the scientific core does not require visualization
extras or a particular quantum-chemistry engine.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

ANGSTROM_TO_BOHR = 1.8897261254578281
DEFAULT_MAX_FILE_BYTES = 1_073_741_824
DEFAULT_MAX_VALUES = 50_000_000
Vector3 = tuple[float, float, float]


class CubeReadError(ValueError):
    """Actionable CUBE parsing/compatibility failure with a stable diagnostic code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CubeAtom:
    """One CUBE geometry record, with Cartesian coordinates normalized to Bohr."""

    atomic_number: int
    nuclear_charge: float
    position_bohr: Vector3


@dataclass(frozen=True, slots=True)
class VolumetricGrid:
    """Transient in-memory scalar fields and their physical lattice.

    values is a NumPy float64 ndarray shaped (nx, ny, nz, nval). The large array
    is deliberately not a Pydantic contract or a database field; persist its raw
    source file as an artifact and keep only compact metadata in result contracts.
    """

    comments: tuple[str, str]
    shape: tuple[int, int, int]
    n_values_per_voxel: int
    origin_bohr: Vector3
    axes_bohr: tuple[Vector3, Vector3, Vector3]
    atoms: tuple[CubeAtom, ...]
    dataset_ids: tuple[int, ...] | None
    source_coordinate_unit: Literal["bohr", "angstrom"]
    values: Any

    def field(self, dataset_index: int = 0) -> Any:
        """Return one scalar field; dataset order follows CUBE DSET_IDS order."""
        if not 0 <= dataset_index < self.n_values_per_voxel:
            raise CubeReadError(
                "VOL.CUBE.DATASET_INDEX_INVALID",
                f"Dataset index {dataset_index} is outside [0, {self.n_values_per_voxel}).",
            )
        return self.values[:, :, :, dataset_index]

    def point_bohr_at(self, indices: Vector3) -> Vector3:
        """Map fractional voxel indices to Cartesian Bohr coordinates."""
        if any(not math.isfinite(index) for index in indices):
            raise ValueError("voxel indices must be finite")
        return cast(
            Vector3,
            tuple(
                self.origin_bohr[component]
                + sum(indices[axis] * self.axes_bohr[axis][component] for axis in range(3))
                for component in range(3)
            ),
        )

    def assert_compatible_lattice(
        self,
        other: VolumetricGrid,
        *,
        coordinate_tolerance_bohr: float = 1e-6,
        nuclear_charge_tolerance: float = 1e-6,
    ) -> None:
        """Require identical voxel indexing and molecular geometry before pointwise math."""
        if (
            not math.isfinite(coordinate_tolerance_bohr)
            or coordinate_tolerance_bohr < 0
            or not math.isfinite(nuclear_charge_tolerance)
            or nuclear_charge_tolerance < 0
        ):
            raise ValueError("grid compatibility tolerances must be finite and non-negative")
        if self.shape != other.shape:
            raise CubeReadError(
                "VOL.CUBE.GRID_MISMATCH",
                f"Grid shapes differ: {self.shape} and {other.shape}.",
            )
        if not _vectors_close(self.origin_bohr, other.origin_bohr, coordinate_tolerance_bohr):
            raise CubeReadError(
                "VOL.CUBE.GRID_MISMATCH", "Cube grid origins differ beyond tolerance."
            )
        if len(self.axes_bohr) != len(other.axes_bohr) or any(
            not _vectors_close(left, right, coordinate_tolerance_bohr)
            for left, right in zip(self.axes_bohr, other.axes_bohr, strict=True)
        ):
            raise CubeReadError(
                "VOL.CUBE.GRID_MISMATCH", "Cube grid axis vectors differ beyond tolerance."
            )
        if len(self.atoms) != len(other.atoms):
            raise CubeReadError("VOL.CUBE.ATOM_GEOMETRY_MISMATCH", "Cube atom counts differ.")
        for index, (left, right) in enumerate(zip(self.atoms, other.atoms, strict=True)):
            if left.atomic_number != right.atomic_number:
                raise CubeReadError(
                    "VOL.CUBE.ATOM_GEOMETRY_MISMATCH",
                    f"Atomic numbers differ at atom record {index}.",
                )
            if not math.isclose(
                left.nuclear_charge,
                right.nuclear_charge,
                rel_tol=0.0,
                abs_tol=nuclear_charge_tolerance,
            ) or not _vectors_close(
                left.position_bohr, right.position_bohr, coordinate_tolerance_bohr
            ):
                raise CubeReadError(
                    "VOL.CUBE.ATOM_GEOMETRY_MISMATCH",
                    f"Atom record {index} differs beyond tolerance.",
                )


def read_cube(
    path: str | Path,
    *,
    length_unit_override: Literal["bohr", "angstrom"] | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_values: int = DEFAULT_MAX_VALUES,
) -> VolumetricGrid:
    """Read a scalar or multi-value CUBE file, including negative-NATOMS datasets.

    Standard positive grid counts default to Bohr coordinates. If every grid count
    is negative, the producer's unit convention is ambiguous across CUBE writers;
    the caller must explicitly supply length_unit_override. Mixed signs are
    rejected. All in-memory coordinates and step vectors are converted to Bohr.
    """
    if max_file_bytes < 1 or max_values < 1:
        raise ValueError("CUBE resource limits must be positive")
    cube_path = Path(path)
    try:
        file_size = cube_path.stat().st_size
    except OSError as exc:
        raise CubeReadError(
            "VOL.CUBE.INPUT_READ_FAILED", f"Cannot stat CUBE input {cube_path}: {exc}"
        ) from exc
    if file_size > max_file_bytes:
        raise CubeReadError(
            "VOL.CUBE.FILE_TOO_LARGE",
            f"CUBE input is {file_size} bytes; configured limit is {max_file_bytes} bytes.",
        )
    try:
        import numpy as np
    except ImportError as exc:  # optional scientific/volumetric dependency
        raise CubeReadError(
            "VOL.CUBE.DEPENDENCY_MISSING",
            "NumPy is required to read volumetric grids; install caddsuite[volumetric].",
        ) from exc

    try:
        stream = cube_path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CubeReadError(
            "VOL.CUBE.INPUT_READ_FAILED", f"Cannot open CUBE input {cube_path}: {exc}"
        ) from exc

    with stream:
        lines = iter(enumerate(stream, start=1))
        comments = (_required_line(lines, "first comment"), _required_line(lines, "second comment"))
        header_line, header = _required_tokens(lines, "atom/origin header")
        if len(header) not in (4, 5):
            raise _error(header_line, "atom/origin header must contain 4 or 5 fields")
        atom_count_signed = _parse_int(header[0], header_line, "atom count")
        atom_count = abs(atom_count_signed)
        if atom_count == 0:
            raise _error(header_line, "zero-atom CUBE files are not supported")
        origin_source = _parse_vector3(header[1:4], header_line, "grid origin")
        n_values = 1 if len(header) == 4 else _parse_int(header[4], header_line, "NVAL")
        if n_values < 1:
            raise _error(header_line, "NVAL must be a positive integer")
        if atom_count_signed < 0 and n_values != 1:
            raise _error(header_line, "negative atom count requires NVAL to be absent or one")

        dimension_counts: list[int] = []
        axes_source: list[Vector3] = []
        for axis_name in ("X", "Y", "Z"):
            line_number, fields = _required_tokens(lines, f"{axis_name} grid axis")
            if len(fields) != 4:
                raise _error(line_number, f"{axis_name} grid axis must contain 4 fields")
            signed_count = _parse_int(fields[0], line_number, f"{axis_name} grid count")
            if signed_count == 0:
                raise _error(line_number, f"{axis_name} grid count must not be zero")
            dimension_counts.append(signed_count)
            axes_source.append(_parse_vector3(fields[1:4], line_number, f"{axis_name} grid vector"))

        signs = {1 if count > 0 else -1 for count in dimension_counts}
        if len(signs) != 1:
            raise CubeReadError(
                "VOL.CUBE.UNIT_CONVENTION_AMBIGUOUS",
                "Grid-count signs are mixed; CUBE length units cannot be inferred safely.",
            )
        signed_unit: Literal["bohr", "angstrom"] | None = (
            "bohr" if dimension_counts[0] > 0 else None
        )
        if length_unit_override is None and signed_unit is None:
            raise CubeReadError(
                "VOL.CUBE.UNIT_CONVENTION_AMBIGUOUS",
                "All grid counts are negative; pass length_unit_override='bohr' or 'angstrom'.",
            )
        if length_unit_override is not None:
            source_unit: Literal["bohr", "angstrom"] = length_unit_override
        elif signed_unit is not None:
            source_unit = signed_unit
        else:
            raise CubeReadError(
                "VOL.CUBE.UNIT_CONVENTION_AMBIGUOUS", "CUBE length unit is unknown."
            )
        scale = ANGSTROM_TO_BOHR if source_unit == "angstrom" else 1.0
        shape = (
            abs(dimension_counts[0]),
            abs(dimension_counts[1]),
            abs(dimension_counts[2]),
        )
        origin_bohr = cast(Vector3, tuple(value * scale for value in origin_source))
        axes_bohr = cast(
            tuple[Vector3, Vector3, Vector3],
            tuple(cast(Vector3, tuple(value * scale for value in axis)) for axis in axes_source),
        )
        if _grid_axes_degenerate(axes_bohr):
            raise CubeReadError(
                "VOL.CUBE.GRID_DEGENERATE", "CUBE grid axis vectors are degenerate."
            )
        grid_points = math.prod(shape)
        total_values = grid_points * n_values
        if total_values > max_values:
            raise CubeReadError(
                "VOL.CUBE.GRID_TOO_LARGE",
                f"CUBE contains {total_values} values; configured limit is {max_values}.",
            )

        atoms: list[CubeAtom] = []
        for atom_index in range(atom_count):
            line_number, fields = _required_tokens(lines, f"atom record {atom_index}")
            if len(fields) != 5:
                raise _error(line_number, f"atom record {atom_index} must contain 5 fields")
            atomic_number = _parse_int(fields[0], line_number, "atomic number")
            if atomic_number < 0:
                raise _error(line_number, "atomic number must be non-negative")
            nuclear_charge = _parse_float(fields[1], line_number, "nuclear charge")
            source_position = _parse_vector3(fields[2:5], line_number, "atom coordinate")
            position = cast(Vector3, tuple(value * scale for value in source_position))
            atoms.append(CubeAtom(atomic_number, nuclear_charge, position))

        dataset_ids: tuple[int, ...] | None = None
        if atom_count_signed < 0:
            first_line_number, first_fields = _next_nonempty_tokens(lines, "dataset identifiers")
            count = _parse_int(first_fields[0], first_line_number, "dataset count")
            if count < 1:
                raise _error(first_line_number, "dataset count must be positive")
            identifier_tokens = first_fields[1:]
            if len(identifier_tokens) > count:
                raise _error(first_line_number, "dataset identifier count exceeds its declaration")
            while len(identifier_tokens) < count:
                line_number, fields = _next_nonempty_tokens(lines, "dataset identifiers")
                if len(identifier_tokens) + len(fields) > count:
                    raise _error(line_number, "dataset identifier count exceeds its declaration")
                identifier_tokens.extend(fields)
            parsed_ids = tuple(
                _parse_int(token, first_line_number, "dataset identifier")
                for token in identifier_tokens
            )
            if any(identifier < 0 for identifier in parsed_ids):
                raise _error(first_line_number, "dataset identifiers must be non-negative")
            if len(set(parsed_ids)) != count:
                raise _error(first_line_number, "dataset identifiers must be unique")
            dataset_ids = parsed_ids
            n_values = count
            total_values = grid_points * n_values
            if total_values > max_values:
                raise CubeReadError(
                    "VOL.CUBE.GRID_TOO_LARGE",
                    f"CUBE contains {total_values} values; configured limit is {max_values}.",
                )

        values = np.empty(total_values, dtype=np.float64)
        cursor = 0

        def consume_data(tokens: list[str], line_number: int) -> None:
            nonlocal cursor
            if not tokens:
                return
            normalized = [token.replace("D", "E").replace("d", "e") for token in tokens]
            try:
                parsed = np.fromstring(" ".join(normalized), sep=" ", dtype=np.float64)
            except ValueError as exc:
                raise _error(line_number, "voxel data contains an invalid number") from exc
            if parsed.size != len(tokens):
                raise _error(line_number, "voxel data contains a malformed token")
            if not bool(np.isfinite(parsed).all()):
                raise _error(line_number, "voxel data contains NaN or infinity")
            end = cursor + parsed.size
            if end > total_values:
                raise _error(line_number, f"too many voxel values; expected exactly {total_values}")
            values[cursor:end] = parsed
            cursor = end

        for line_number, line in lines:
            if not line.split():
                continue
            consume_data(line.split(), line_number)
        if cursor != total_values:
            raise CubeReadError(
                "VOL.CUBE.VALUE_COUNT_MISMATCH",
                f"CUBE contains {cursor} voxel values; expected exactly {total_values}.",
            )

    reshaped = values.reshape((*shape, n_values), order="C")
    return VolumetricGrid(
        comments=comments,
        shape=shape,
        n_values_per_voxel=n_values,
        origin_bohr=origin_bohr,
        axes_bohr=axes_bohr,
        atoms=tuple(atoms),
        dataset_ids=dataset_ids,
        source_coordinate_unit=source_unit,
        values=reshaped,
    )


def _required_line(lines: Iterator[tuple[int, str]], label: str) -> str:
    try:
        _line_number, line = next(lines)
    except StopIteration as exc:
        raise CubeReadError("VOL.CUBE.HEADER_TRUNCATED", f"CUBE ended before {label}.") from exc
    return line.rstrip("\r\n")


def _required_tokens(lines: Iterator[tuple[int, str]], label: str) -> tuple[int, list[str]]:
    try:
        line_number, line = next(lines)
    except StopIteration as exc:
        raise CubeReadError("VOL.CUBE.HEADER_TRUNCATED", f"CUBE ended before {label}.") from exc
    tokens = line.split()
    if not tokens:
        raise _error(line_number, f"{label} is blank")
    return line_number, tokens


def _next_nonempty_tokens(lines: Iterator[tuple[int, str]], label: str) -> tuple[int, list[str]]:
    for line_number, line in lines:
        tokens = line.split()
        if tokens:
            return line_number, tokens
    raise CubeReadError("VOL.CUBE.HEADER_TRUNCATED", f"CUBE ended before {label}.")


def _parse_int(token: str, line_number: int, label: str) -> int:
    try:
        return int(token)
    except ValueError as exc:
        raise _error(line_number, f"{label} must be an integer") from exc


def _parse_vector3(tokens: list[str], line_number: int, label: str) -> Vector3:
    if len(tokens) != 3:
        raise _error(line_number, f"{label} must contain exactly 3 values")
    return (
        _parse_float(tokens[0], line_number, label),
        _parse_float(tokens[1], line_number, label),
        _parse_float(tokens[2], line_number, label),
    )


def _parse_float(token: str, line_number: int, label: str) -> float:
    try:
        value = float(token.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise _error(line_number, f"{label} must be numeric") from exc
    if not math.isfinite(value):
        raise _error(line_number, f"{label} must be finite")
    return value


def _vectors_close(
    left: Vector3,
    right: Vector3,
    tolerance: float,
) -> bool:
    return all(
        math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance) for a, b in zip(left, right, strict=True)
    )


def _grid_axes_degenerate(axes: tuple[Vector3, Vector3, Vector3]) -> bool:
    a, b, c = axes
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    norm_product = math.prod(
        math.sqrt(sum(component * component for component in axis)) for axis in axes
    )
    return norm_product == 0.0 or abs(determinant) <= norm_product * 1e-12


def _error(line_number: int, message: str) -> CubeReadError:
    return CubeReadError(
        "VOL.CUBE.INVALID_CONTENT",
        f"CUBE line {line_number}: {message}.",
    )
