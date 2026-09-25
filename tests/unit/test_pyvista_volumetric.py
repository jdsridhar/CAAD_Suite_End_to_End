from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from caddsuite.adapters.visualization.pyvista_volumetric import (
    PyVistaVolumetricRenderer,
    VolumetricRenderError,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.visualization import (
    CubeRenderInput,
    FrontierOrbitalRenderRequest,
    FukuiRenderRequest,
    MEPRenderRequest,
)
from caddsuite.domain.identity import new_ulid

np = pytest.importorskip("numpy")


def _cube_file(path: Path, field: object, *, step: float = 0.1) -> str:
    values = np.asarray(field, dtype=np.float64)
    nx, ny, nz = values.shape
    lines = [
        "synthetic molecule",
        "analytic scalar field",
        "1 -1.0 -1.0 -1.0",
        f"{nx} {step} 0 0",
        f"{ny} 0 {step} 0",
        f"{nz} 0 0 {step}",
        "6 6.0 0.0 0.0 0.0",
    ]
    flat = values.ravel(order="C")
    lines.extend(
        " ".join(f"{value:.8e}" for value in flat[start : start + 6])
        for start in range(0, len(flat), 6)
    )
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs(path: Path, role: str, digest: str) -> CubeRenderInput:
    return CubeRenderInput(artifact=ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest))


def _analytic_fields() -> tuple[object, object, object, object, object]:
    coords = np.linspace(-1.0, 1.0, 21)
    x, y, z = np.meshgrid(coords, coords, coords, indexing="ij")
    radius_squared = x * x + y * y + z * z
    density = 0.25 * np.exp(-radius_squared)
    homo = x * np.exp(-radius_squared)
    lumo = y * np.exp(-radius_squared)
    localized = 0.04 * np.exp(-radius_squared / 0.2)
    anion = density + localized
    cation = density - localized
    return homo, lumo, density, anion, cation


def test_render_requests_reject_hash_mismatch_and_incompatible_grids(tmp_path: Path) -> None:
    field = np.ones((2, 2, 2), dtype=np.float64)
    first_path = tmp_path / "first.cube"
    second_path = tmp_path / "second.cube"
    first_hash = _cube_file(first_path, field)
    second_hash = _cube_file(second_path, field, step=0.2)
    first = _inputs(first_path, "density", first_hash)
    second = _inputs(second_path, "esp", second_hash)
    renderer = PyVistaVolumetricRenderer()
    request = MEPRenderRequest(id=new_ulid(), density=first, esp=second)
    with pytest.raises(VolumetricRenderError) as error:
        renderer.render(
            request,
            cube_paths={
                str(first.artifact.artifact_id): first_path,
                str(second.artifact.artifact_id): second_path,
            },
            output_directory=tmp_path / "out",
        )
    assert error.value.code == "VOL.CUBE.GRID_MISMATCH"

    changed = _inputs(first_path, "density", "0" * 64)
    request = MEPRenderRequest(id=new_ulid(), density=changed, esp=second)
    with pytest.raises(VolumetricRenderError) as hash_error:
        renderer.render(
            request,
            cube_paths={
                str(changed.artifact.artifact_id): first_path,
                str(second.artifact.artifact_id): second_path,
            },
            output_directory=tmp_path / "out",
        )
    assert hash_error.value.code == "VISUALIZATION.INPUT_HASH_MISMATCH"


def test_offscreen_fmo_mep_and_fukui_renderers(tmp_path: Path) -> None:
    pytest.importorskip("pyvista")
    pytest.importorskip("scipy")
    pytest.importorskip("skimage")
    homo, lumo, density, anion, cation = _analytic_fields()
    content = {
        "homo": homo,
        "lumo": lumo,
        "density": density,
        "esp": np.meshgrid(
            np.linspace(-1.0, 1.0, 21),
            np.linspace(-1.0, 1.0, 21),
            np.linspace(-1.0, 1.0, 21),
            indexing="ij",
        )[0],
        "anion": anion,
        "cation": cation,
    }
    paths: dict[str, Path] = {}
    inputs: dict[str, CubeRenderInput] = {}
    for role, field in content.items():
        path = tmp_path / f"{role}.cube"
        digest = _cube_file(path, field)
        source = _inputs(path, role, digest)
        paths[str(source.artifact.artifact_id)] = path
        inputs[role] = source

    renderer = PyVistaVolumetricRenderer()
    requests = (
        FrontierOrbitalRenderRequest(
            id=new_ulid(),
            homo=inputs["homo"],
            lumo=inputs["lumo"],
            isovalue_au=0.03,
            size_pixels=(400, 200),
            show_molecular_skeleton=False,
        ),
        MEPRenderRequest(
            id=new_ulid(),
            density=inputs["density"],
            esp=inputs["esp"],
            density_isovalue_e_bohr3=0.05,
            size_pixels=(300, 300),
        ),
        FukuiRenderRequest(
            id=new_ulid(),
            neutral_density=inputs["density"],
            charged_density=inputs["anion"],
            sign="plus",
            isovalue_e_bohr3=0.01,
            size_pixels=(300, 300),
        ),
        FukuiRenderRequest(
            id=new_ulid(),
            neutral_density=inputs["density"],
            charged_density=inputs["cation"],
            sign="minus",
            isovalue_e_bohr3=0.01,
            size_pixels=(300, 300),
        ),
    )
    for request in requests:
        receipt = renderer.render(request, cube_paths=paths, output_directory=tmp_path / "figures")
        assert receipt.path.is_file()
        assert receipt.path.stat().st_size > 1000
        assert hashlib.sha256(receipt.path.read_bytes()).hexdigest() == receipt.sha256
        assert len(receipt.input_hashes) == 2
        with pytest.raises(VolumetricRenderError) as error:
            renderer.render(request, cube_paths=paths, output_directory=tmp_path / "figures")
        assert error.value.code == "VISUALIZATION.OUTPUT_ALREADY_EXISTS"
