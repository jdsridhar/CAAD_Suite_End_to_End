from __future__ import annotations

from pathlib import Path

import pytest

from caddsuite.analysis.cube import (
    ANGSTROM_TO_BOHR,
    CubeReadError,
    read_cube,
)

pytest.importorskip("numpy")


def _write_cube(tmp_path: Path, text: str, name: str = "field.cube") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="ascii")
    return path


def _positive_cube(
    *,
    data: str = "1.0D+00 2.0D+00",
    header: str = "1 0.0 0.0 0.0",
    axes: str = "2 0.5 0 0\n1 0 0.5 0\n1 0 0 0.5",
    atom: str = "6 6.0 0.0 0.0 0.0",
) -> str:
    return f"molecule\ntest field\n{header}\n{axes}\n{atom}\n{data}\n"


def test_reads_positive_natoms_and_normalizes_units_to_bohr(tmp_path: Path) -> None:
    grid = read_cube(_write_cube(tmp_path, _positive_cube()))

    assert grid.shape == (2, 1, 1)
    assert grid.dataset_ids is None
    assert grid.source_coordinate_unit == "bohr"
    assert grid.values.shape == (2, 1, 1, 1)
    assert grid.field().ravel().tolist() == [1.0, 2.0]
    assert grid.axes_bohr[0] == (0.5, 0.0, 0.0)
    assert grid.point_bohr_at((1.0, 1.0, 1.0)) == (0.5, 0.5, 0.5)


def test_reads_skew_axis_transform(tmp_path: Path) -> None:
    axes = "2 0.5 0 0\n1 0.25 0.5 0\n1 0 0 0.5"
    grid = read_cube(_write_cube(tmp_path, _positive_cube(axes=axes)))

    assert grid.point_bohr_at((1.0, 1.0, 1.0)) == (0.75, 0.5, 0.5)


def test_reads_negative_natoms_and_wrapped_interleaved_dataset_ids(tmp_path: Path) -> None:
    text = (
        "molecule\nnegative natoms\n-1 0 0 0\n"
        "2 0.5 0 0\n1 0 0.5 0\n1 0 0 0.5\n"
        "6 6.0 0 0 0\n2 17\n4\n"
        "1.0D+00 10 2.0D+00 20\n"
    )
    grid = read_cube(_write_cube(tmp_path, text))

    assert grid.dataset_ids == (17, 4)
    assert grid.n_values_per_voxel == 2
    assert grid.values.shape == (2, 1, 1, 2)
    assert grid.field(0).ravel().tolist() == [1.0, 2.0]
    assert grid.field(1).ravel().tolist() == [10.0, 20.0]


def test_negative_natoms_accepts_explicit_nval_one(tmp_path: Path) -> None:
    text = _positive_cube(header="-1 0 0 0 1", data="1 7\n1 2")
    grid = read_cube(_write_cube(tmp_path, text))

    assert grid.dataset_ids == (7,)
    assert grid.n_values_per_voxel == 1
    assert grid.field().ravel().tolist() == [1.0, 2.0]


def test_reads_explicit_nval_for_positive_atom_count(tmp_path: Path) -> None:
    text = _positive_cube(header="1 0 0 0 2", data="1 11 2 22")
    grid = read_cube(_write_cube(tmp_path, text))

    assert grid.n_values_per_voxel == 2
    assert grid.dataset_ids is None
    assert grid.field(1).ravel().tolist() == [11.0, 22.0]


def test_requires_explicit_unit_for_negative_grid_counts(tmp_path: Path) -> None:
    text = _positive_cube(axes="-2 0.25 0 0\n-1 0 0.25 0\n-1 0 0 0.25")
    path = _write_cube(tmp_path, text)

    with pytest.raises(CubeReadError) as error:
        read_cube(path)
    assert error.value.code == "VOL.CUBE.UNIT_CONVENTION_AMBIGUOUS"

    grid = read_cube(path, length_unit_override="angstrom")
    assert grid.source_coordinate_unit == "angstrom"
    assert grid.axes_bohr[0][0] == pytest.approx(0.25 * ANGSTROM_TO_BOHR)


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        (_positive_cube(data="1.0"), "VOL.CUBE.VALUE_COUNT_MISMATCH"),
        (_positive_cube(data="1 2 3"), "VOL.CUBE.INVALID_CONTENT"),
        (_positive_cube(data="1 nan"), "VOL.CUBE.INVALID_CONTENT"),
        (_positive_cube(axes="0 0.5 0 0\n1 0 0.5 0\n1 0 0 0.5"), "VOL.CUBE.INVALID_CONTENT"),
        (
            "mol\nfield\n-1 0 0 0\n2 1 0 0\n1 0 1 0\n1 0 0 1\n6 6 0 0 0\n2 4 4\n1 2 3 4\n",
            "VOL.CUBE.INVALID_CONTENT",
        ),
        (
            "mol\nfield\n-1 0 0 0\n2 1 0 0\n1 0 1 0\n1 0 0 1\n6 6 0 0 0\n2 4\n1 2 3 4\n",
            "VOL.CUBE.INVALID_CONTENT",
        ),
        (_positive_cube(atom="6 6 0 0"), "VOL.CUBE.INVALID_CONTENT"),
        ("only one line\n", "VOL.CUBE.HEADER_TRUNCATED"),
    ],
)
def test_rejects_malformed_or_inconsistent_cube_data(
    tmp_path: Path, text: str, expected_code: str
) -> None:
    with pytest.raises(CubeReadError) as error:
        read_cube(_write_cube(tmp_path, text))
    assert error.value.code == expected_code


def test_rejects_mixed_grid_count_signs(tmp_path: Path) -> None:
    text = _positive_cube(axes="-2 0.5 0 0\n1 0 0.5 0\n1 0 0 0.5")
    with pytest.raises(CubeReadError) as error:
        read_cube(_write_cube(tmp_path, text))
    assert error.value.code == "VOL.CUBE.UNIT_CONVENTION_AMBIGUOUS"


def test_rejects_noninvertible_grid_axes(tmp_path: Path) -> None:
    axes = "2 1 0 0\n1 2 0 0\n1 3 0 0"
    with pytest.raises(CubeReadError) as error:
        read_cube(_write_cube(tmp_path, _positive_cube(axes=axes)))
    assert error.value.code == "VOL.CUBE.GRID_DEGENERATE"


@pytest.mark.parametrize(
    ("left_cube", "right_cube", "expected_code"),
    [
        (_positive_cube(), _positive_cube(header="1 0.1 0 0"), "VOL.CUBE.GRID_MISMATCH"),
        (
            _positive_cube(),
            _positive_cube(axes="2 0.6 0 0\n1 0 0.5 0\n1 0 0 0.5"),
            "VOL.CUBE.GRID_MISMATCH",
        ),
        (
            _positive_cube(),
            _positive_cube(atom="8 8.0 0.0 0.0 0.0"),
            "VOL.CUBE.ATOM_GEOMETRY_MISMATCH",
        ),
        (
            _positive_cube(),
            _positive_cube(atom="6 6.0 0.1 0.0 0.0"),
            "VOL.CUBE.ATOM_GEOMETRY_MISMATCH",
        ),
    ],
)
def test_requires_compatible_full_grid_and_atom_geometry(
    tmp_path: Path, left_cube: str, right_cube: str, expected_code: str
) -> None:
    left = read_cube(_write_cube(tmp_path, left_cube, "left.cube"))
    right = read_cube(_write_cube(tmp_path, right_cube, "right.cube"))

    with pytest.raises(CubeReadError) as error:
        left.assert_compatible_lattice(right)
    assert error.value.code == expected_code


def test_dataset_index_and_resource_limit_are_validated(tmp_path: Path) -> None:
    grid = read_cube(_write_cube(tmp_path, _positive_cube()))
    with pytest.raises(CubeReadError) as index_error:
        grid.field(2)
    assert index_error.value.code == "VOL.CUBE.DATASET_INDEX_INVALID"

    with pytest.raises(CubeReadError) as limit_error:
        read_cube(_write_cube(tmp_path, _positive_cube()), max_values=1)
    assert limit_error.value.code == "VOL.CUBE.GRID_TOO_LARGE"
