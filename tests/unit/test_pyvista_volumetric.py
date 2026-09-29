from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from caddsuite.adapters.visualization import pyvista_volumetric as renderer_module
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


def test_render_rejects_missing_staged_cube(tmp_path: Path) -> None:
    field = np.ones((2, 2, 2), dtype=np.float64)
    path = tmp_path / "density.cube"
    digest = _cube_file(path, field)
    source = _inputs(path, "density", digest)
    second = _inputs(path, "esp", digest)
    request = MEPRenderRequest(id=new_ulid(), density=source, esp=second)

    with pytest.raises(VolumetricRenderError) as missing_path:
        PyVistaVolumetricRenderer().render(
            request, cube_paths={}, output_directory=tmp_path / "out"
        )
    assert missing_path.value.code == "VISUALIZATION.INPUT_ARTIFACT_MISSING"


def test_render_rejects_malformed_cube_with_parser_error_code(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.cube"
    malformed.write_text("not a cube file\n", encoding="ascii")
    source = _inputs(malformed, "density", hashlib.sha256(malformed.read_bytes()).hexdigest())
    second = _inputs(malformed, "esp", source.artifact.sha256 or "")
    request = MEPRenderRequest(id=new_ulid(), density=source, esp=second)

    with pytest.raises(VolumetricRenderError) as error:
        PyVistaVolumetricRenderer().render(
            request,
            cube_paths={
                str(source.artifact.artifact_id): malformed,
                str(second.artifact.artifact_id): malformed,
            },
            output_directory=tmp_path / "out",
        )
    assert error.value.code == "VOL.CUBE.HEADER_TRUNCATED"


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


def _valid_mep_inputs(tmp_path: Path, *, dataset_index: int = 0):
    field = np.ones((2, 2, 2), dtype=np.float64)
    density_path = tmp_path / "density.cube"
    esp_path = tmp_path / "esp.cube"
    density_hash = _cube_file(density_path, field)
    esp_hash = _cube_file(esp_path, field * 2.0)
    density = CubeRenderInput(
        artifact=ArtifactRef(artifact_id=new_ulid(), role="density", sha256=density_hash),
        dataset_index=dataset_index,
    )
    esp = _inputs(esp_path, "esp", esp_hash)
    request = MEPRenderRequest(id=new_ulid(), density=density, esp=esp)
    paths = {
        str(density.artifact.artifact_id): density_path,
        str(esp.artifact.artifact_id): esp_path,
    }
    return request, paths


def _fake_optional_modules(monkeypatch) -> None:
    from types import SimpleNamespace

    modules = {
        "numpy": object(),
        "pyvista": SimpleNamespace(__version__="test"),
        "scipy.ndimage": SimpleNamespace(map_coordinates=object()),
        "skimage.measure": object(),
    }
    monkeypatch.setattr(renderer_module, "import_module", modules.__getitem__)


def test_renderer_preserves_cube_dataset_error_code(tmp_path: Path) -> None:
    request, paths = _valid_mep_inputs(tmp_path, dataset_index=1)
    with pytest.raises(VolumetricRenderError) as error:
        PyVistaVolumetricRenderer().render(
            request, cube_paths=paths, output_directory=tmp_path / "figures"
        )
    assert error.value.code == "VOL.CUBE.DATASET_INDEX_INVALID"


def test_renderer_reports_missing_expected_input_hash(tmp_path: Path) -> None:
    request, paths = _valid_mep_inputs(tmp_path)
    source = ArtifactRef.model_construct(
        artifact_id=request.density.artifact.artifact_id,
        role="density",
        sha256=None,
    )
    request = MEPRenderRequest.model_construct(
        id=request.id,
        density=CubeRenderInput.model_construct(artifact=source, dataset_index=0),
        esp=request.esp,
    )
    with pytest.raises(VolumetricRenderError) as error:
        PyVistaVolumetricRenderer().render(
            request, cube_paths=paths, output_directory=tmp_path / "figures"
        )
    assert error.value.code == "VISUALIZATION.INPUT_HASH_MISSING"


def test_renderer_translates_optional_dependency_import_error(tmp_path: Path, monkeypatch) -> None:
    request, paths = _valid_mep_inputs(tmp_path)
    original = renderer_module.import_module

    def missing_pyvista(name: str):
        if name == "pyvista":
            raise ImportError("simulated absent renderer")
        return original(name)

    monkeypatch.setattr(renderer_module, "import_module", missing_pyvista)
    with pytest.raises(VolumetricRenderError) as error:
        PyVistaVolumetricRenderer().render(
            request, cube_paths=paths, output_directory=tmp_path / "figures"
        )
    assert error.value.code == "VISUALIZATION.DEPENDENCY_MISSING"
    assert not (tmp_path / "figures").exists()


def test_renderer_translates_missing_staged_file_read_error(tmp_path: Path) -> None:
    request, paths = _valid_mep_inputs(tmp_path)
    missing = tmp_path / "removed.cube"
    paths[str(request.density.artifact.artifact_id)] = missing
    with pytest.raises(VolumetricRenderError) as error:
        PyVistaVolumetricRenderer().render(
            request, cube_paths=paths, output_directory=tmp_path / "figures"
        )
    assert error.value.code == "VISUALIZATION.INPUT_READ_FAILED"


def test_renderer_reports_output_path_that_is_a_file(tmp_path: Path, monkeypatch) -> None:
    request, paths = _valid_mep_inputs(tmp_path)
    _fake_optional_modules(monkeypatch)
    output = tmp_path / "not-a-directory"
    output.write_text("protected", encoding="utf-8")
    with pytest.raises(VolumetricRenderError) as error:
        PyVistaVolumetricRenderer().render(request, cube_paths=paths, output_directory=output)
    assert error.value.code == "VISUALIZATION.OUTPUT_WRITE_FAILED"
    assert error.value.retryable


def test_renderer_refuses_existing_output_before_rendering(tmp_path: Path, monkeypatch) -> None:
    request, paths = _valid_mep_inputs(tmp_path)
    _fake_optional_modules(monkeypatch)
    output = tmp_path / "figures"
    output.mkdir()
    destination = output / f"vol-{request.id}-mep.png"
    destination.write_bytes(b"preserve")
    with pytest.raises(VolumetricRenderError) as error:
        PyVistaVolumetricRenderer().render(request, cube_paths=paths, output_directory=output)
    assert error.value.code == "VISUALIZATION.OUTPUT_ALREADY_EXISTS"
    assert destination.read_bytes() == b"preserve"


def test_renderer_cleans_temporary_figure_when_backend_fails(tmp_path: Path, monkeypatch) -> None:
    request, paths = _valid_mep_inputs(tmp_path)
    _fake_optional_modules(monkeypatch)

    def backend_failure(*args, **kwargs):
        raise RuntimeError("simulated off-screen backend error")

    monkeypatch.setattr(renderer_module, "_render_to_path", backend_failure)
    output = tmp_path / "figures"
    with pytest.raises(VolumetricRenderError) as error:
        PyVistaVolumetricRenderer().render(request, cube_paths=paths, output_directory=output)
    assert error.value.code == "VISUALIZATION.RENDER_FAILED"
    assert list(output.iterdir()) == []


def test_molecular_frame_handles_single_atom_and_degenerate_axis_geometry() -> None:
    from caddsuite.analysis.cube import CubeAtom, VolumetricGrid

    def make_grid(atoms):
        return VolumetricGrid(
            comments=("test", "test"),
            shape=(1, 1, 1),
            n_values_per_voxel=1,
            origin_bohr=(0.0, 0.0, 0.0),
            axes_bohr=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            atoms=tuple(atoms),
            dataset_ids=None,
            source_coordinate_unit="bohr",
            values=None,
        )

    atom = CubeAtom(atomic_number=6, nuclear_charge=6.0, position_bohr=(1.0, 2.0, 3.0))
    rotation, center, warnings = renderer_module._molecular_frame(make_grid([atom]), np)
    assert np.array_equal(rotation, np.eye(3))
    assert np.allclose(center, np.asarray(atom.position_bohr) * renderer_module.BOHR_TO_ANGSTROM)
    assert warnings == ()

    linear = make_grid([CubeAtom(6, 6.0, (0.0, 0.0, 0.0)), CubeAtom(6, 6.0, (2.0, 0.0, 0.0))])
    rotation, _center, warnings = renderer_module._molecular_frame(linear, np)
    assert np.allclose(rotation @ rotation.T, np.eye(3))
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    assert warnings == ("Principal-axis orientation is degenerate and not unique.",)


def test_surface_mesh_maps_cube_lattice_to_angstrom_and_vtk_faces() -> None:
    from caddsuite.analysis.cube import VolumetricGrid

    grid = VolumetricGrid(
        comments=("test", "test"),
        shape=(2, 2, 2),
        n_values_per_voxel=1,
        origin_bohr=(1.0, 2.0, 3.0),
        axes_bohr=((0.5, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 2.0)),
        atoms=(),
        dataset_ids=None,
        source_coordinate_unit="bohr",
        values=None,
    )

    class PolyData:
        def __init__(self, points, faces):
            self.points = points
            self.faces = faces

    FakePyVista = type("FakePyVista", (), {"PolyData": PolyData})

    vertices = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    faces = np.asarray([[0, 1, 2]], dtype=np.int32)
    mesh = renderer_module._surface_mesh(
        grid, vertices, faces, np.eye(3), np.zeros(3), np, FakePyVista
    )

    expected_bohr = np.asarray(grid.origin_bohr) + vertices @ np.asarray(grid.axes_bohr)
    assert np.allclose(mesh.points, expected_bohr * renderer_module.BOHR_TO_ANGSTROM)
    assert np.array_equal(mesh.faces, np.asarray([[3, 0, 1, 2]]))


def test_surface_extraction_returns_none_when_requested_level_is_absent() -> None:
    class MissingSurface:
        @staticmethod
        def marching_cubes(field, *, level):
            raise ValueError(f"no surface at {level}")

    assert renderer_module._surface(np.ones((2, 2, 2)), 2.0, MissingSurface) is None


def test_molecular_frame_rejects_atomic_number_outside_periodic_table() -> None:
    from types import SimpleNamespace

    grid = SimpleNamespace(
        atoms=(SimpleNamespace(atomic_number=119, position_bohr=(0.0, 0.0, 0.0)),)
    )
    with pytest.raises(VolumetricRenderError) as error:
        renderer_module._molecular_frame(grid, np)
    assert error.value.code == "VISUALIZATION.ELEMENT_UNSUPPORTED"
