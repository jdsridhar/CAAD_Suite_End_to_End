"""Optional PyVista renderer for hash-verified, engine-neutral CUBE artifacts."""

from __future__ import annotations

import hashlib
import os
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any

from caddsuite.analysis.cube import CubeReadError, VolumetricGrid, read_cube
from caddsuite.contracts.base import SoftwareRef
from caddsuite.contracts.visualization import (
    CubeRenderInput,
    FrontierOrbitalRenderRequest,
    FukuiRenderRequest,
    MEPRenderRequest,
)
from caddsuite.domain.enums import SoftwareKind
from caddsuite.ports.volumetric_visualization import (
    RenderedVolumetricFigure,
    VolumetricRenderCapabilities,
    VolumetricRenderRequest,
)

BOHR_TO_ANGSTROM = 0.529177210903
_ORBITAL_POSITIVE = "#2D5FA8"
_ORBITAL_NEGATIVE = "#B93B2C"
_CPK_COLORS = {
    "H": "#FFFFFF",
    "C": "#4D4D4D",
    "N": "#3050F8",
    "O": "#FF0D0D",
    "F": "#90E050",
    "P": "#FF8000",
    "S": "#FFC832",
    "Cl": "#1FF01F",
    "Br": "#A62929",
    "I": "#940094",
    "B": "#FFB5B5",
    "Si": "#F0C8A0",
    "Na": "#AB5CF2",
    "Mg": "#8AFF00",
    "K": "#8F40D4",
    "Ca": "#3DFF00",
    "Fe": "#E06633",
    "Zn": "#7D80B0",
}
_COVALENT_RADII_ANGSTROM = {
    "H": 0.31,
    "B": 0.84,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "Si": 1.11,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Br": 1.20,
    "I": 1.39,
    "Na": 1.66,
    "Mg": 1.41,
    "K": 2.03,
    "Ca": 1.76,
    "Fe": 1.32,
    "Zn": 1.22,
}
_ELEMENTS = (
    "X",
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
    "Np",
    "Pu",
    "Am",
    "Cm",
    "Bk",
    "Cf",
    "Es",
    "Fm",
    "Md",
    "No",
    "Lr",
    "Rf",
    "Db",
    "Sg",
    "Bh",
    "Hs",
    "Mt",
    "Ds",
    "Rg",
    "Cn",
    "Nh",
    "Fl",
    "Mc",
    "Lv",
    "Ts",
    "Og",
)


class VolumetricRenderError(ValueError):
    """Actionable volumetric rendering/input error with a stable code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class PyVistaVolumetricRenderer:
    """Render FMO, MEP, and Fukui figures without knowing the cube's QM producer."""

    adapter_id = "caddsuite.visualization.pyvista.volumetric"
    version = "0.1.0"
    capabilities = VolumetricRenderCapabilities()

    def render(
        self,
        request: VolumetricRenderRequest,
        *,
        cube_paths: dict[str, Path],
        output_directory: Path,
    ) -> RenderedVolumetricFigure:
        inputs = _request_inputs(request)
        grids: list[VolumetricGrid] = []
        fields: list[Any] = []
        input_hashes: list[str] = []
        for source in inputs:
            artifact_id = str(source.artifact.artifact_id)
            path = cube_paths.get(artifact_id)
            if path is None:
                raise VolumetricRenderError(
                    "VISUALIZATION.INPUT_ARTIFACT_MISSING",
                    f"No staged file was supplied for cube artifact {artifact_id}.",
                )
            expected_hash = source.artifact.sha256
            if expected_hash is None:
                raise VolumetricRenderError(
                    "VISUALIZATION.INPUT_HASH_MISSING",
                    f"Cube artifact {artifact_id} has no SHA-256 hash.",
                )
            digest = _sha256(path)
            if digest != expected_hash:
                raise VolumetricRenderError(
                    "VISUALIZATION.INPUT_HASH_MISMATCH",
                    f"Cube file hash does not match artifact {artifact_id}.",
                )
            try:
                grid = read_cube(path)
                field = grid.field(source.dataset_index)
            except CubeReadError as exc:
                raise VolumetricRenderError(exc.code, str(exc)) from exc
            grids.append(grid)
            fields.append(field)
            input_hashes.append(digest)

        for grid in grids[1:]:
            try:
                grids[0].assert_compatible_lattice(grid)
            except CubeReadError as exc:
                raise VolumetricRenderError(exc.code, str(exc)) from exc

        try:
            np = import_module("numpy")
            pv = import_module("pyvista")
            map_coordinates = import_module("scipy.ndimage").map_coordinates
            measure = import_module("skimage.measure")
        except ImportError as exc:
            raise VolumetricRenderError(
                "VISUALIZATION.DEPENDENCY_MISSING",
                "Install caddsuite[volumetric] for NumPy, SciPy, scikit-image, and PyVista.",
            ) from exc

        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise VolumetricRenderError(
                "VISUALIZATION.OUTPUT_WRITE_FAILED",
                f"Could not create figure directory {output_directory}: {exc}",
                retryable=True,
            ) from exc
        kind = _request_kind(request)
        final_path = output_directory / f"vol-{request.id}-{kind}.png"
        if final_path.exists() or final_path.is_symlink():
            raise VolumetricRenderError(
                "VISUALIZATION.OUTPUT_ALREADY_EXISTS",
                f"Refusing to overwrite an existing figure: {final_path.name}.",
            )
        temporary_path: Path | None = None
        plotter: Any | None = None
        warnings: list[str] = []
        try:
            with tempfile.NamedTemporaryFile(
                dir=output_directory, prefix=".volumetric-", suffix=".png", delete=False
            ) as stream:
                temporary_path = Path(stream.name)
            plotter, warnings = _render_to_path(
                request, grids, fields, temporary_path, np, pv, measure, map_coordinates
            )
            try:
                os.link(temporary_path, final_path)
            except FileExistsError as exc:
                raise VolumetricRenderError(
                    "VISUALIZATION.OUTPUT_ALREADY_EXISTS",
                    f"Refusing to overwrite an existing figure: {final_path.name}.",
                ) from exc
        except VolumetricRenderError:
            raise
        except OSError as exc:
            raise VolumetricRenderError(
                "VISUALIZATION.OUTPUT_WRITE_FAILED",
                f"Could not write figure in {output_directory}: {exc}",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise VolumetricRenderError(
                "VISUALIZATION.RENDER_FAILED", f"PyVista could not render {kind}: {exc}"
            ) from exc
        finally:
            if plotter is not None:
                plotter.close()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return RenderedVolumetricFigure(
            path=final_path,
            sha256=_sha256(final_path),
            renderer=SoftwareRef(
                name="PyVista", version=str(pv.__version__), kind=SoftwareKind.LIBRARY
            ),
            adapter_id=self.adapter_id,
            adapter_version=self.version,
            request=request,
            input_artifact_ids=tuple(str(source.artifact.artifact_id) for source in inputs),
            input_hashes=tuple(input_hashes),
            warnings=tuple(warnings),
        )


def _request_inputs(request: VolumetricRenderRequest) -> tuple[CubeRenderInput, ...]:
    if isinstance(request, FrontierOrbitalRenderRequest):
        return request.homo, request.lumo
    if isinstance(request, MEPRenderRequest):
        return request.density, request.esp
    if isinstance(request, FukuiRenderRequest):
        return request.neutral_density, request.charged_density
    raise VolumetricRenderError(
        "VISUALIZATION.REQUEST_UNSUPPORTED", f"Unsupported request type {type(request).__name__}."
    )


def _request_kind(request: VolumetricRenderRequest) -> str:
    if isinstance(request, FrontierOrbitalRenderRequest):
        return "frontier-orbitals"
    if isinstance(request, MEPRenderRequest):
        return "mep"
    if isinstance(request, FukuiRenderRequest):
        return "fukui-" + request.sign
    raise VolumetricRenderError(
        "VISUALIZATION.REQUEST_UNSUPPORTED", f"Unsupported request type {type(request).__name__}."
    )


def _render_to_path(
    request: VolumetricRenderRequest,
    grids: list[VolumetricGrid],
    fields: list[Any],
    output_path: Path,
    np: Any,
    pv: Any,
    measure: Any,
    map_coordinates: Any,
) -> tuple[Any, list[str]]:
    rotation, center, frame_warnings = _molecular_frame(grids[0], np)
    warnings = list(frame_warnings)
    plotter: Any | None = None
    try:
        if isinstance(request, FrontierOrbitalRenderRequest):
            plotter = pv.Plotter(off_screen=True, window_size=request.size_pixels, shape=(1, 2))
            for column, (field, label, energy) in enumerate(
                (
                    (fields[0], "HOMO", request.homo_energy_eV),
                    (fields[1], "LUMO", request.lumo_energy_eV),
                )
            ):
                plotter.subplot(0, column)
                lobe_count = 0
                for sign, level, color in (
                    ("positive", request.isovalue_au, "#2D5FA8"),
                    ("negative", -request.isovalue_au, "#B93B2C"),
                ):
                    surface = _surface(field, level, measure)
                    if surface is None:
                        warnings.append(f"{label}: no {sign} lobe at isovalue {level:g} a.u.")
                        continue
                    vertices, faces = surface
                    mesh = _surface_mesh(grids[column], vertices, faces, rotation, center, np, pv)
                    plotter.add_mesh(mesh, color=color, opacity=0.6, smooth_shading=True)
                    lobe_count += 1
                if lobe_count == 0:
                    raise VolumetricRenderError(
                        "VISUALIZATION.SURFACE_NOT_FOUND",
                        f"{label} has no isosurface at {request.isovalue_au:g} a.u.",
                    )
                if request.show_molecular_skeleton:
                    warnings.extend(_add_skeleton(plotter, grids[0], rotation, center, np, pv))
                title = label if energy is None else f"{label} ({energy:.3f} eV)"
                plotter.add_text(title, position="upper_edge", font_size=14, color="black")
                _set_camera(plotter)
            plotter.set_background("white")
        elif isinstance(request, MEPRenderRequest):
            surface = _surface(fields[0], request.density_isovalue_e_bohr3, measure)
            if surface is None:
                raise VolumetricRenderError(
                    "VISUALIZATION.SURFACE_NOT_FOUND",
                    "Density field has no surface at the requested isovalue.",
                )
            vertices, faces = surface
            mesh = _surface_mesh(grids[0], vertices, faces, rotation, center, np, pv)
            esp_values = map_coordinates(fields[1], vertices.T, order=1)
            low, high = request.esp_clip_au
            mesh["ESP (a.u.)"] = np.clip(esp_values, low, high)
            plotter = pv.Plotter(off_screen=True, window_size=request.size_pixels)
            plotter.add_mesh(
                mesh,
                scalars="ESP (a.u.)",
                cmap=request.colormap,
                clim=(low, high),
                smooth_shading=True,
                scalar_bar_args={"title": "ESP (a.u.)", "color": "black"},
            )
            if request.show_molecular_skeleton:
                warnings.extend(_add_skeleton(plotter, grids[0], rotation, center, np, pv))
            _set_camera(plotter)
            plotter.set_background("white")
        elif isinstance(request, FukuiRenderRequest):
            if request.sign == "plus":
                difference = fields[1] - fields[0]
                color = "#2D5FA8"
                label = "f+ (nucleophilic attack site)"
            else:
                difference = fields[0] - fields[1]
                color = "#B93B2C"
                label = "f- (electrophilic attack site)"
            surface = _surface(difference, request.isovalue_e_bohr3, measure)
            if surface is None:
                raise VolumetricRenderError(
                    "VISUALIZATION.SURFACE_NOT_FOUND",
                    f"{label} has no positive surface at the requested isovalue.",
                )
            vertices, faces = surface
            mesh = _surface_mesh(grids[0], vertices, faces, rotation, center, np, pv)
            plotter = pv.Plotter(off_screen=True, window_size=request.size_pixels)
            plotter.add_mesh(mesh, color=color, opacity=0.6, smooth_shading=True)
            if request.show_molecular_skeleton:
                warnings.extend(_add_skeleton(plotter, grids[0], rotation, center, np, pv))
            plotter.add_text(label, position="upper_edge", font_size=13, color="black")
            _set_camera(plotter)
            plotter.set_background("white")
        else:
            raise VolumetricRenderError(
                "VISUALIZATION.REQUEST_UNSUPPORTED",
                f"Unsupported request type {type(request).__name__}.",
            )
        plotter.screenshot(str(output_path))
        return plotter, warnings
    except Exception:
        if plotter is not None:
            plotter.close()
        raise


def _surface(field: Any, level: float, measure: Any) -> Any:
    try:
        vertices, faces, _normals, _values = measure.marching_cubes(field, level=level)
    except (ValueError, RuntimeError):
        return None
    return vertices, faces


def _surface_mesh(
    grid: VolumetricGrid,
    vertices: Any,
    faces: Any,
    rotation: Any,
    center: Any,
    np: Any,
    pv: Any,
) -> Any:
    origin = np.asarray(grid.origin_bohr, dtype=np.float64)
    axes = np.asarray(grid.axes_bohr, dtype=np.float64)
    points = (origin + vertices @ axes) * BOHR_TO_ANGSTROM
    points = (points - center) @ rotation.T
    vtk_faces = np.hstack([np.full((faces.shape[0], 1), 3, dtype=np.int64), faces.astype(np.int64)])
    return pv.PolyData(points, vtk_faces)


def _molecular_frame(grid: VolumetricGrid, np: Any) -> tuple[Any, Any, tuple[str, ...]]:
    if any(atom.atomic_number >= len(_ELEMENTS) for atom in grid.atoms):
        raise VolumetricRenderError(
            "VISUALIZATION.ELEMENT_UNSUPPORTED", "CUBE contains an atomic number outside 0–118."
        )
    atom_positions = (
        np.asarray([atom.position_bohr for atom in grid.atoms], dtype=np.float64) * BOHR_TO_ANGSTROM
    )
    heavy = atom_positions[np.asarray([atom.atomic_number > 1 for atom in grid.atoms])]
    points = heavy if len(heavy) >= 3 else atom_positions
    if len(points) < 2:
        return np.eye(3), atom_positions.mean(axis=0), ()
    centered = points - points.mean(axis=0)
    eigenvalues, eigenvectors = np.linalg.eigh(centered.T @ centered)
    order = np.argsort(eigenvalues)[::-1]
    rotation = eigenvectors[:, order].T
    for row in range(3):
        pivot = int(np.argmax(np.abs(rotation[row])))
        if rotation[row, pivot] < 0:
            rotation[row] *= -1
    if np.linalg.det(rotation) < 0:
        rotation[-1] *= -1
    scale = max(float(eigenvalues[-1]), 1.0)
    degenerate = any(
        abs(float(eigenvalues[order[i]] - eigenvalues[order[i + 1]])) <= scale * 1e-8
        for i in range(2)
    )
    warnings = ("Principal-axis orientation is degenerate and not unique.",) if degenerate else ()
    return rotation, atom_positions.mean(axis=0), warnings


def _add_skeleton(
    plotter: Any, grid: VolumetricGrid, rotation: Any, center: Any, np: Any, pv: Any
) -> list[str]:
    symbols = [_ELEMENTS[atom.atomic_number] for atom in grid.atoms]
    coordinates = (
        np.asarray([atom.position_bohr for atom in grid.atoms], dtype=np.float64) * BOHR_TO_ANGSTROM
    )
    coordinates = (coordinates - center) @ rotation.T
    for symbol in sorted(set(symbols)):
        indices = [index for index, item in enumerate(symbols) if item == symbol]
        points = pv.PolyData(coordinates[indices])
        radius = 0.16 if symbol == "H" else 0.22
        color = _CPK_COLORS.get(symbol, "#808080")
        glyphs = points.glyph(
            geom=pv.Sphere(radius=radius, theta_resolution=12, phi_resolution=12),
            scale=False,
            orient=False,
        )
        plotter.add_mesh(glyphs, color=color, smooth_shading=True, specular=0.3)

    warnings: list[str] = []
    unknown = False
    for i in range(len(grid.atoms)):
        symbol_i = symbols[i]
        for j in range(i + 1, len(grid.atoms)):
            symbol_j = symbols[j]
            radius_i = _COVALENT_RADII_ANGSTROM.get(symbol_i)
            radius_j = _COVALENT_RADII_ANGSTROM.get(symbol_j)
            if radius_i is None or radius_j is None:
                unknown = True
                continue
            distance = float(np.linalg.norm(coordinates[i] - coordinates[j]))
            if distance >= 1.3 * (radius_i + radius_j) or distance < 1e-6:
                continue
            vector = coordinates[j] - coordinates[i]
            cylinder = pv.Cylinder(
                center=(coordinates[i] + coordinates[j]) / 2,
                direction=vector,
                radius=0.09,
                height=distance,
            )
            plotter.add_mesh(cylinder, color="#BFBFBF", smooth_shading=True, specular=0.3)
    if unknown:
        warnings.append(
            "Some display bonds were omitted because no covalent-radius heuristic is configured."
        )
    return warnings


def _set_camera(plotter: Any) -> None:
    plotter.camera.azimuth = 35
    plotter.camera.elevation = 20
    plotter.camera.roll = 0
    plotter.enable_parallel_projection()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise VolumetricRenderError(
            "VISUALIZATION.INPUT_READ_FAILED", f"Could not read artifact {path}: {exc}"
        ) from exc
    return digest.hexdigest()
