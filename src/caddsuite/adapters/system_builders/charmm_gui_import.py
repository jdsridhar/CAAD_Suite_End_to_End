"""Conservative parser for CHARMM-GUI GROMACS system bundles.

The importer reads registered bytes only. It does not run GROMACS, regenerate parameters,
or modify the bundle.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import NoReturn

from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.md import (
    AtomSelection,
    BoxSpec,
    ComponentForceField,
    ForceFieldComponent,
    ForceFieldFamily,
    MDProtocol,
    MDStage,
    MDStageKind,
    MDSystem,
    Parameterization,
)
from caddsuite.contracts.system import SystemBuildRequest, SystemBuildResult
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import AdapterContext, ExecutionPlan
from caddsuite.ports.system_builder import SystemBuilderCapabilities
from caddsuite.validation import default_registry
from caddsuite.validation.force_field_profiles import CHARMM_GUI_GROMACS_PROFILE_ID
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class SystemBundleImportError(ValueError):
    """The bundle is incomplete, ambiguous, inconsistent, or unsupported."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _GroAtom:
    def __init__(self, residue_name: str) -> None:
        self.residue_name = residue_name


def _fail(code: str, message: str) -> NoReturn:
    raise SystemBundleImportError(code, message)


def _safe_path(value: str) -> str:
    if not value or value.startswith("/") or "\\" in value:
        _fail("SYSTEM_BUNDLE.UNSAFE_PATH", f"unsafe bundle path {value!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail("SYSTEM_BUNDLE.UNSAFE_PATH", f"unsafe bundle path {value!r}")
    if PurePosixPath(value).as_posix() != value:
        _fail("SYSTEM_BUNDLE.UNSAFE_PATH", f"non-canonical bundle path {value!r}")
    return value


def _utf8(payload: bytes, path: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail("SYSTEM_BUNDLE.INVALID_TEXT", f"{path!r} is not UTF-8 text: {exc}")
    raise AssertionError("unreachable")


def _checked_files(
    request: SystemBuildRequest, bundle_files: Mapping[str, bytes]
) -> dict[str, bytes]:
    refs: dict[str, ArtifactRef] = {}
    for raw_path, ref in request.source_artifacts.items():
        path = _safe_path(raw_path)
        if path in refs:
            _fail("SYSTEM_BUNDLE.DUPLICATE_PATH", f"duplicate bundle path {path!r}")
        if ref.sha256 is None:
            _fail("SYSTEM_BUNDLE.MISSING_HASH", f"artifact {path!r} has no SHA-256")
        refs[path] = ref
    files: dict[str, bytes] = {}
    for raw_path, payload in bundle_files.items():
        path = _safe_path(raw_path)
        if path not in refs:
            _fail("SYSTEM_BUNDLE.UNREGISTERED_FILE", f"{path!r} is not registered in the request")
        if hashlib.sha256(payload).hexdigest() != refs[path].sha256:
            _fail(
                "SYSTEM_BUNDLE.HASH_MISMATCH", f"bytes differ from registered digest for {path!r}"
            )
        files[path] = payload
    missing = sorted(set(refs) - set(files))
    if missing:
        _fail("SYSTEM_BUNDLE.MISSING_FILE", f"registered artifacts are absent: {missing}")
    required = {
        "topol.top",
        "step3_input.gro",
        "index.ndx",
        "step4.0_minimization.mdp",
        "step4.1_equilibration.mdp",
        "step5_production.mdp",
        "toppar/forcefield.itp",
    }
    missing_required = sorted(required - set(files))
    if missing_required:
        _fail("SYSTEM_BUNDLE.MISSING_REQUIRED_FILE", f"required files absent: {missing_required}")
    return files


def _topology_texts(files: Mapping[str, bytes]) -> dict[str, str]:
    texts: dict[str, str] = {}
    visiting: set[str] = set()
    include_rx = re.compile(r'^\s*#include\s+"([^"]+)"\s*$')

    def visit(path: str) -> None:
        if path in visiting:
            _fail("SYSTEM_BUNDLE.INCLUDE_CYCLE", f"recursive topology include {path!r}")
        if path in texts:
            return
        if path not in files:
            _fail("SYSTEM_BUNDLE.MISSING_INCLUDE", f"included topology file {path!r} is absent")
        visiting.add(path)
        text = _utf8(files[path], path)
        texts[path] = text
        parent = PurePosixPath(path).parent
        for line_number, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.split(";", 1)[0].strip()
            if not line.startswith("#include"):
                continue
            match = include_rx.fullmatch(line)
            if match is None:
                _fail(
                    "SYSTEM_BUNDLE.UNSUPPORTED_INCLUDE",
                    f"unsupported include syntax at {path}:{line_number}; expected "
                    "a quoted relative path",
                )
            include = match.group(1)
            if include.startswith("/") or "\\" in include:
                _fail("SYSTEM_BUNDLE.UNSAFE_INCLUDE", f"unsafe include at {path}:{line_number}")
            resolved = include if str(parent) == "." else f"{parent}/{include}"
            visit(_safe_path(resolved))
        visiting.remove(path)

    visit("topol.top")
    return texts


def _parse_topology(
    texts: Mapping[str, str],
) -> tuple[dict[str, tuple[int, float]], dict[str, int]]:
    types: dict[str, tuple[int, float]] = {}
    counts: dict[str, int] = {}
    for path, text in texts.items():
        section = ""
        current_type: str | None = None
        atom_count = 0
        total_charge = 0.0
        conditional_depth = 0
        for number, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.split(";", 1)[0].strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith(("#ifdef", "#ifndef", "#if ")):
                conditional_depth += 1
                continue
            if low.startswith("#endif"):
                conditional_depth -= 1
                if conditional_depth < 0:
                    _fail(
                        "SYSTEM_BUNDLE.PREPROCESSOR_INVALID", f"unmatched #endif at {path}:{number}"
                    )
                continue
            if line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                if section == "atoms" and current_type is not None:
                    types[current_type] = (atom_count, total_charge)
                    current_type, atom_count, total_charge = None, 0, 0.0
                section = line[1:-1].strip().lower()
                if conditional_depth and section in {"atoms", "moleculetype", "molecules"}:
                    _fail(
                        "SYSTEM_BUNDLE.CONDITIONAL_TOPOLOGY_UNSUPPORTED",
                        f"conditional atom topology at {path}:{number}",
                    )
                continue
            fields = line.split()
            if path == "topol.top" and section == "molecules":
                if len(fields) < 2:
                    _fail(
                        "SYSTEM_BUNDLE.MOLECULES_INVALID",
                        f"malformed molecule row at {path}:{number}",
                    )
                try:
                    count = int(fields[1])
                except ValueError:
                    _fail(
                        "SYSTEM_BUNDLE.MOLECULES_INVALID",
                        f"invalid molecule count at {path}:{number}",
                    )
                if count < 1 or fields[0] in counts:
                    _fail(
                        "SYSTEM_BUNDLE.MOLECULES_INVALID",
                        f"invalid/duplicate molecule row at {path}:{number}",
                    )
                counts[fields[0]] = count
            elif section == "moleculetype":
                if current_type is not None:
                    _fail(
                        "SYSTEM_BUNDLE.MOLECULETYPE_INVALID",
                        f"unexpected molecule name at {path}:{number}",
                    )
                current_type = fields[0]
            elif section == "atoms":
                if current_type is None or len(fields) < 7:
                    _fail("SYSTEM_BUNDLE.ATOMS_INVALID", f"malformed atom row at {path}:{number}")
                try:
                    charge = float(fields[6])
                except ValueError:
                    _fail("SYSTEM_BUNDLE.ATOMS_INVALID", f"invalid charge at {path}:{number}")
                if not math.isfinite(charge):
                    _fail("SYSTEM_BUNDLE.ATOMS_INVALID", f"non-finite charge at {path}:{number}")
                atom_count += 1
                total_charge += charge
        if section == "atoms" and current_type is not None:
            types[current_type] = (atom_count, total_charge)
        if conditional_depth:
            _fail("SYSTEM_BUNDLE.PREPROCESSOR_INVALID", f"unclosed conditional block in {path}")
    if not counts:
        _fail("SYSTEM_BUNDLE.MOLECULES_MISSING", "topol.top has no [ molecules ] rows")
    for name, _count in counts.items():
        if name not in types or types[name][0] < 1:
            _fail(
                "SYSTEM_BUNDLE.MOLECULETYPE_MISSING",
                f"molecule type {name!r} has no parsed [ atoms ]",
            )
    return types, counts


def _parse_gro(payload: bytes) -> tuple[list[_GroAtom], BoxSpec]:
    lines = _utf8(payload, "step3_input.gro").splitlines()
    try:
        natoms = int(lines[1].strip())
    except (IndexError, ValueError):
        _fail("SYSTEM_BUNDLE.GRO_INVALID", "GRO atom-count header is invalid")
    if natoms < 1 or len(lines) < natoms + 3:
        _fail("SYSTEM_BUNDLE.GRO_INVALID", "GRO atom count does not match its coordinate rows")
    atoms: list[_GroAtom] = []
    for row, line in enumerate(lines[2 : 2 + natoms], start=3):
        if len(line) < 44:
            _fail("SYSTEM_BUNDLE.GRO_INVALID", f"GRO atom row {row} is too short")
        name = line[5:10].strip()
        try:
            xyz = (float(line[20:28]), float(line[28:36]), float(line[36:44]))
        except ValueError:
            _fail("SYSTEM_BUNDLE.GRO_INVALID", f"GRO row {row} has invalid coordinates")
        if not name or not all(math.isfinite(value) for value in xyz):
            _fail("SYSTEM_BUNDLE.GRO_INVALID", f"GRO row {row} has an invalid residue/coordinate")
        atoms.append(_GroAtom(name))
    try:
        b = tuple(float(x) for x in lines[2 + natoms].split())
    except (IndexError, ValueError):
        _fail("SYSTEM_BUNDLE.GRO_BOX_INVALID", "GRO box row is missing or invalid")
    if len(b) == 3:
        xx, yy, zz = b
        vectors = ((xx, 0.0, 0.0), (0.0, yy, 0.0), (0.0, 0.0, zz))
    elif len(b) == 9:
        # GRO stores v1(x), v2(y), v3(z), v1(y), v1(z), v2(x), v2(z), v3(x), v3(y).
        xx, yy, zz, v1y, v1z, v2x, v2z, v3x, v3y = b
        if any(abs(value) >= 1e-12 for value in (v1y, v1z, v2z)):
            _fail(
                "SYSTEM_BUNDLE.GRO_BOX_INVALID",
                "GROMACS GRO box is not in the supported reduced-triclinic form",
            )
        vectors = ((xx, v1y, v1z), (v2x, yy, v2z), (v3x, v3y, zz))
    else:
        _fail("SYSTEM_BUNDLE.GRO_BOX_INVALID", f"expected 3 or 9 box values, got {len(b)}")
    det = (
        vectors[0][0] * (vectors[1][1] * vectors[2][2] - vectors[1][2] * vectors[2][1])
        - vectors[0][1] * (vectors[1][0] * vectors[2][2] - vectors[1][2] * vectors[2][0])
        + vectors[0][2] * (vectors[1][0] * vectors[2][1] - vectors[1][1] * vectors[2][0])
    )
    if not math.isfinite(det) or det <= 0:
        _fail("SYSTEM_BUNDLE.GRO_BOX_INVALID", "periodic box must have positive finite volume")
    rectangular = all(abs(vectors[i][j]) < 1e-12 for i in range(3) for j in range(3) if i != j)
    shape = "rectangular" if rectangular else "triclinic"
    return atoms, BoxSpec(shape=shape, vectors_nm=vectors)


def _parse_ndx(payload: bytes, natoms: int) -> dict[str, tuple[int, ...]]:
    text = _utf8(payload, "index.ndx")
    groups: dict[str, list[int]] = {}
    current: str | None = None
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"\[\s*(.+?)\s*\]", line)
        if match:
            current = match.group(1)
            if current in groups:
                _fail("SYSTEM_BUNDLE.NDX_DUPLICATE_GROUP", f"duplicate index group {current!r}")
            groups[current] = []
        elif current is None:
            _fail("SYSTEM_BUNDLE.NDX_INVALID", f"indices precede a group header at line {number}")
        else:
            try:
                groups[current].extend(int(item) for item in line.split())
            except ValueError:
                _fail("SYSTEM_BUNDLE.NDX_INVALID", f"non-integer index at line {number}")
    parsed: dict[str, tuple[int, ...]] = {}
    for name, indices in groups.items():
        if not indices or len(indices) != len(set(indices)):
            _fail("SYSTEM_BUNDLE.NDX_INVALID", f"index group {name!r} is empty or repeats atoms")
        if any(i < 1 or i > natoms for i in indices):
            _fail("SYSTEM_BUNDLE.NDX_RANGE", f"index group {name!r} contains an out-of-range atom")
        parsed[name] = tuple(indices)
    return parsed


def _parse_mdp(payload: bytes, path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw_line in enumerate(_utf8(payload, path).splitlines(), 1):
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            _fail("SYSTEM_BUNDLE.MDP_INVALID", f"expected key=value at {path}:{number}")
        key, value = (part.strip() for part in line.split("=", 1))
        key = key.lower()
        if not key or not value:
            _fail("SYSTEM_BUNDLE.MDP_INVALID", f"empty key/value at {path}:{number}")
        if key in result and result[key] != value:
            _fail("SYSTEM_BUNDLE.MDP_DUPLICATE_SETTING", f"conflicting {key!r} entries in {path}")
        result[key] = value
    return result


def _number(
    settings: Mapping[str, str], key: str, path: str, required: bool = False
) -> float | None:
    raw = settings.get(key)
    if raw is None:
        if required:
            _fail("SYSTEM_BUNDLE.MDP_SETTING_MISSING", f"{path} is missing {key!r}")
        return None
    try:
        value = float(raw)
    except ValueError:
        _fail("SYSTEM_BUNDLE.MDP_SETTING_INVALID", f"{path} has invalid numeric value for {key!r}")
    if not math.isfinite(value):
        _fail("SYSTEM_BUNDLE.MDP_SETTING_INVALID", f"{path} has non-finite {key!r}")
    return value


def _uniform(settings: Mapping[str, str], key: str, path: str) -> float | None:
    raw = settings.get(key)
    if raw is None:
        return None
    try:
        values = tuple(float(item) for item in raw.split())
    except ValueError:
        _fail("SYSTEM_BUNDLE.MDP_SETTING_INVALID", f"{path} has invalid vector {key!r}")
    if not values or any(not math.isfinite(x) for x in values):
        _fail("SYSTEM_BUNDLE.MDP_SETTING_INVALID", f"{path} has invalid vector {key!r}")
    if any(not math.isclose(x, values[0], rel_tol=1e-9, abs_tol=1e-12) for x in values[1:]):
        _fail("SYSTEM_BUNDLE.MDP_VECTOR_UNSUPPORTED", f"{path} has non-uniform {key!r} values")
    return values[0]


def _stage(path: str, values: Mapping[str, str]) -> MDStage:
    integrator = values.get("integrator")
    if integrator is None:
        _fail("SYSTEM_BUNDLE.MDP_SETTING_MISSING", f"{path} has no integrator")
    tcoupl = values.get("tcoupl", "no").lower()
    pcoupl = values.get("pcoupl", "no").lower()
    if integrator.lower() in {"steep", "cg", "l-bfgs"}:
        kind = MDStageKind.MINIMIZATION
    elif "production" in PurePosixPath(path).name.lower():
        # Stage role is part of the normalized protocol even when production is NPT.
        kind = MDStageKind.PRODUCTION
    elif pcoupl != "no":
        kind = MDStageKind.NPT
    elif tcoupl != "no":
        kind = MDStageKind.NVT
    else:
        _fail(
            "SYSTEM_BUNDLE.PROTOCOL_STAGE_UNSUPPORTED",
            f"{path} ensemble is not represented by MDStage",
        )
    try:
        nsteps = int(values["nsteps"])
    except (KeyError, ValueError):
        _fail("SYSTEM_BUNDLE.MDP_SETTING_INVALID", f"{path} needs integer nsteps")
    dt_ps = _number(values, "dt", path)
    temperature = _uniform(values, "ref_t", path)
    pressure = _uniform(values, "ref_p", path)
    nonbonded_keys = {
        "cutoff-scheme",
        "nstlist",
        "vdwtype",
        "vdw-modifier",
        "rvdw_switch",
        "rvdw",
        "rlist",
        "coulombtype",
        "rcoulomb",
        "pbc",
        "constraints",
        "constraint_algorithm",
        "tc_grps",
        "tau_t",
        "tau_p",
        "pcoupltype",
        "compressibility",
        "ref_t",
        "ref_p",
        "define",
    }
    try:
        return MDStage(
            kind=kind,
            integrator=integrator,
            timestep_fs=None if dt_ps is None else dt_ps * 1000.0,
            n_steps=nsteps,
            temperature_K=(
                temperature
                if kind in {MDStageKind.NVT, MDStageKind.NPT, MDStageKind.PRODUCTION}
                else None
            ),
            thermostat=values.get("tcoupl") if tcoupl != "no" else None,
            pressure_bar=(
                pressure
                if kind is MDStageKind.NPT or (kind is MDStageKind.PRODUCTION and pcoupl != "no")
                else None
            ),
            barostat=values.get("pcoupl") if pcoupl != "no" else None,
            constraints=values.get("constraints"),
            hmr=None,
            restraints=values.get("define"),
            nonbonded={key: value for key, value in values.items() if key in nonbonded_keys},
        )
    except ValueError as exc:
        _fail("SYSTEM_BUNDLE.PROTOCOL_INVALID", f"cannot normalize {path}: {exc}")


def _text_param(request: SystemBuildRequest, key: str) -> str:
    value = request.parameters.get(key)
    if not isinstance(value, str) or not value.strip():
        _fail("SYSTEM_BUNDLE.PARAMETER_MISSING", f"request must explicitly set {key!r}")
    return value.strip()


def _list_param(request: SystemBuildRequest, key: str) -> tuple[str, ...]:
    value = request.parameters.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(x, str) or not x.strip() for x in value)
    ):
        _fail("SYSTEM_BUNDLE.PARAMETER_MISSING", f"request must set non-empty string list {key!r}")
    return tuple(x.strip() for x in value if isinstance(x, str))


def import_charmm_gui_gromacs_bundle(
    *,
    request: SystemBuildRequest,
    complex_model: Complex,
    bundle_files: Mapping[str, bytes],
    adapter_version: str = "0.1.0",
) -> SystemBuildResult:
    """Normalize one explicitly selected CHARMM-GUI bundle, retaining all source references."""
    if request.mode != "import":
        _fail("SYSTEM_BUNDLE.MODE_MISMATCH", "CHARMM-GUI bundle importer requires mode='import'")
    for key in ("id", "compound_id", "form_id", "target_id", "pose_id"):
        request_key = "complex_id" if key == "id" else key
        if getattr(request, request_key) != getattr(complex_model, key):
            _fail("SYSTEM_BUNDLE.LINEAGE_MISMATCH", f"request {request_key} differs from Complex")
    files = _checked_files(request, bundle_files)
    top_texts = _topology_texts(files)
    forcefield = _utf8(files["toppar/forcefield.itp"], "toppar/forcefield.itp")
    if "CHARMM FF in GROMACS format" not in forcefield:
        _fail(
            "SYSTEM_BUNDLE.FORCEFIELD_UNRECOGNIZED",
            "CHARMM-GUI CHARMM marker absent from forcefield.itp",
        )
    if request.parameters.get("ff_family") != ForceFieldFamily.CHARMM.value:
        _fail(
            "SYSTEM_BUNDLE.FORCEFIELD_MISMATCH",
            "only an explicitly selected CHARMM family is supported",
        )
    method = {
        key: _text_param(request, key)
        for key in (
            "protein_ff",
            "ligand_method",
            "ligand_charge_model",
            "water_model",
            "ion_parameters",
        )
    }
    ligand_resnames = _list_param(request, "ligand_resnames")
    ligand_types = _list_param(request, "ligand_molecule_types")
    protein_types = _list_param(request, "protein_molecule_types")
    molecule_types, molecule_counts = _parse_topology(top_texts)
    gro_atoms, box = _parse_gro(files["step3_input.gro"])
    total_atoms = 0
    total_charge = 0.0
    composition: dict[str, int] = {}
    for name, count in molecule_counts.items():
        atoms, charge = molecule_types[name]
        total_atoms += atoms * count
        total_charge += charge * count
        composition[name] = count
    if total_atoms != len(gro_atoms):
        _fail(
            "SYSTEM_BUNDLE.ATOM_COUNT_MISMATCH",
            f"topology has {total_atoms} atoms; GRO has {len(gro_atoms)}",
        )

    selection_path = _text_param(request, "selection_index_path")
    if selection_path not in files:
        _fail(
            "SYSTEM_BUNDLE.SELECTION_INDEX_MISSING", f"selection index {selection_path!r} is absent"
        )
    groups = _parse_ndx(files[selection_path], len(gro_atoms))
    lig_group = request.selections.get("ligand")
    prot_group = request.selections.get("protein")
    if not lig_group or not prot_group:
        _fail("SYSTEM_BUNDLE.SELECTION_REQUIRED", "name ligand and protein index groups explicitly")
    if lig_group not in groups or prot_group not in groups:
        _fail(
            "SYSTEM_BUNDLE.SELECTION_MISSING",
            f"requested groups {lig_group!r}/{prot_group!r} not found",
        )
    expected_ligand = tuple(
        i for i, atom in enumerate(gro_atoms, start=1) if atom.residue_name in ligand_resnames
    )
    ligand_indices = groups[lig_group]
    if set(expected_ligand) != set(ligand_indices):
        _fail(
            "SYSTEM_BUNDLE.LIGAND_SELECTION_MISMATCH",
            "ligand index group differs from explicitly named GRO residue(s)",
        )
    if any(name not in molecule_counts for name in ligand_types):
        _fail(
            "SYSTEM_BUNDLE.LIGAND_MOLECULE_MISSING",
            "declared ligand molecule type absent from topology",
        )
    ligand_atom_count = sum(molecule_types[n][0] * molecule_counts[n] for n in ligand_types)
    if (
        ligand_atom_count != len(ligand_indices)
        or ligand_atom_count != complex_model.ligand_atom_count
    ):
        _fail(
            "SYSTEM_BUNDLE.LIGAND_ATOM_COUNT_MISMATCH",
            "ligand topology, index group and Complex atom counts disagree",
        )
    if any(name not in molecule_counts for name in protein_types):
        _fail(
            "SYSTEM_BUNDLE.PROTEIN_MOLECULE_MISSING",
            "declared protein molecule type absent from topology",
        )
    protein_atom_count = sum(molecule_types[n][0] * molecule_counts[n] for n in protein_types)
    protein_indices = groups[prot_group]
    if protein_atom_count != len(protein_indices):
        _fail(
            "SYSTEM_BUNDLE.PROTEIN_SELECTION_MISMATCH",
            "protein topology and index-group atom counts disagree",
        )
    if set(protein_indices) & set(ligand_indices):
        _fail("SYSTEM_BUNDLE.SELECTION_OVERLAP", "protein and ligand selections overlap")

    mdp_names = (
        "step4.0_minimization.mdp",
        "step4.1_equilibration.mdp",
        "step5_production.mdp",
    )
    stages = tuple(_stage(name, _parse_mdp(files[name], name)) for name in mdp_names)
    try:
        protocol = MDProtocol(stages=stages)
    except ValueError as exc:
        _fail("SYSTEM_BUNDLE.PROTOCOL_INVALID", str(exc))

    refs = dict(request.source_artifacts)
    manual_software = SoftwareRef(
        name="CHARMM-GUI",
        version=str(
            request.parameters.get("parameterizer_version", "not recorded in source bundle")
        ),
        kind=SoftwareKind.MANUAL_STEP,
        license_class=LicenseClass.ACADEMIC_NONCOMMERCIAL,
    )
    builder = SoftwareRef(
        name="caddsuite.charmm_gui_gromacs_import",
        version=adapter_version,
        kind=SoftwareKind.ADAPTER,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )
    try:
        parameterization = Parameterization(
            id=new_ulid(),
            ff_family=ForceFieldFamily.CHARMM,
            protein_ff=method["protein_ff"],
            ligand_method=method["ligand_method"],
            ligand_charge_model=method["ligand_charge_model"],
            water_model=method["water_model"],
            ion_parameters=method["ion_parameters"],
            tool=manual_software,
            compatibility_profile_id=CHARMM_GUI_GROMACS_PROFILE_ID,
            component_force_fields={
                ForceFieldComponent.PROTEIN: ComponentForceField(
                    family=ForceFieldFamily.CHARMM, name=method["protein_ff"]
                ),
                ForceFieldComponent.LIGAND: ComponentForceField(
                    family=ForceFieldFamily.CHARMM, name=method["ligand_method"]
                ),
                ForceFieldComponent.WATER: ComponentForceField(
                    family=ForceFieldFamily.CHARMM, name=method["water_model"]
                ),
                ForceFieldComponent.IONS: ComponentForceField(
                    family=ForceFieldFamily.CHARMM, name=method["ion_parameters"]
                ),
            },
            quality={
                "topology_format": "GROMACS",
                "topology_includes": sorted(top_texts),
                "molecule_atom_counts": {
                    name: molecule_types[name][0] for name in sorted(molecule_types)
                },
                "declared_parameterization": method,
                "hydrogen_mass_repartitioning": "not inferred from timestep",
                "selection_index_path": selection_path,
                "ligand_resnames": list(ligand_resnames),
                "ligand_molecule_types": list(ligand_types),
                "protein_molecule_types": list(protein_types),
            },
            artifacts={path: ref for path, ref in refs.items() if path.startswith("toppar/")},
        )
        system = MDSystem(
            id=new_ulid(),
            complex_id=complex_model.id,
            parameterization_id=parameterization.id,
            builder=builder,
            box=box,
            n_atoms=total_atoms,
            net_charge=total_charge,
            composition=composition,
            selections={
                "ligand": AtomSelection(
                    description=(
                        f"[{lig_group}] cross-checked against GRO residue names "
                        "and Complex atom count"
                    ),
                    n_atoms=len(ligand_indices),
                    indices=refs[selection_path],
                    verified=True,
                ),
                "protein": AtomSelection(
                    description=(
                        f"[{prot_group}] cross-checked against topology protein molecule counts"
                    ),
                    n_atoms=len(protein_indices),
                    indices=refs[selection_path],
                    verified=True,
                ),
            },
            engine_inputs={"gromacs": dict(refs)},
        )
        issues = tuple(
            default_registry().run(
                "system_build",
                {"parameterization": parameterization, "md_system": system},
            )
        )
        if any(
            stage.timestep_fs is not None and stage.timestep_fs > 2 and stage.hmr is None
            for stage in stages
        ):
            issues = (
                *issues,
                ValidationIssue(
                    code="MD.HMR_UNVERIFIED",
                    severity=Severity.WARNING,
                    subject=SubjectRef(kind="md_system", id=system.id),
                    message=(
                        "a timestep above 2 fs is present but hydrogen-mass repartitioning "
                        "is not explicitly established"
                    ),
                    evidence={"timestep_fs": max(stage.timestep_fs or 0 for stage in stages)},
                    remediation=(
                        "Inspect topology hydrogen masses and record the HMR "
                        "method/status before production.",
                    ),
                    rule_version="1.0.0",
                ),
            )
        return SystemBuildResult(
            id=new_ulid(),
            request_id=request.id,
            complex_id=complex_model.id,
            builder=builder,
            parameterization=parameterization,
            system=system,
            protocol=protocol,
            raw_artifacts=refs,
            normalized_artifacts={},
            validation_issues=issues,
        )
    except ValueError as exc:
        _fail("SYSTEM_BUNDLE.NORMALIZATION_FAILED", str(exc))


def bundle_validation_issue(error: SystemBundleImportError, request_id: str) -> ValidationIssue:
    """Map parser failures to structured blocking validation issues."""
    return ValidationIssue(
        code=error.code,
        severity=Severity.BLOCKER,
        subject=SubjectRef(kind="system_build_request", id=request_id),
        message=str(error),
        remediation=(
            "Correct the registered bundle or explicit system-building configuration and retry.",
        ),
        rule_version="1.0.0",
    )


class CharmmGuiGromacsImportAdapter:
    """StageAdapter implementation for safe, read-only bundle import."""

    adapter_id = "system_builder.charmm_gui_gromacs_import"
    version = "0.1.0"
    capabilities: SystemBuilderCapabilities

    def __init__(self) -> None:
        self.capabilities = SystemBuilderCapabilities(
            mode="import",
            input_formats=("charmm_gui_gromacs_bundle",),
            output_engine_formats=("gromacs",),
            force_field_families=(ForceFieldFamily.CHARMM,),
            ligand_parameterization_methods=("CGenFF",),
        )

    def _inputs(
        self, context: AdapterContext
    ) -> tuple[SystemBuildRequest, Complex, dict[str, bytes]]:
        request = next(
            (value for value in context.inputs.values() if isinstance(value, SystemBuildRequest)),
            None,
        )
        complex_model = next(
            (value for value in context.inputs.values() if isinstance(value, Complex)),
            None,
        )
        if request is None or complex_model is None:
            _fail(
                "SYSTEM_BUNDLE.CONTEXT_INCOMPLETE",
                "context must include SystemBuildRequest and Complex",
            )
        root = context.working_directory.resolve()
        files: dict[str, bytes] = {}
        for raw_path in request.source_artifacts:
            relative = _safe_path(raw_path)
            candidate = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
            try:
                candidate.relative_to(root)
            except ValueError:
                _fail(
                    "SYSTEM_BUNDLE.UNSAFE_PATH",
                    f"source path escapes staging directory: {relative!r}",
                )
            if not candidate.is_file():
                _fail(
                    "SYSTEM_BUNDLE.MISSING_FILE",
                    f"source artifact is not a regular file: {relative!r}",
                )
            files[relative] = candidate.read_bytes()
        return request, complex_model, files

    def validate_input(self, context: AdapterContext) -> tuple[ValidationIssue, ...]:
        try:
            request, complex_model, files = self._inputs(context)
            result = import_charmm_gui_gromacs_bundle(
                request=request,
                complex_model=complex_model,
                bundle_files=files,
                adapter_version=self.version,
            )
            return result.validation_issues
        except SystemBundleImportError as exc:
            request_candidate = next(
                (
                    value
                    for value in context.inputs.values()
                    if isinstance(value, SystemBuildRequest)
                ),
                None,
            )
            return (
                bundle_validation_issue(
                    exc, request_candidate.id if request_candidate else "unknown"
                ),
            )
        except OSError as exc:
            request_candidate = next(
                (
                    value
                    for value in context.inputs.values()
                    if isinstance(value, SystemBuildRequest)
                ),
                None,
            )
            error = SystemBundleImportError("SYSTEM_BUNDLE.FILE_IO", str(exc))
            return (
                bundle_validation_issue(
                    error, request_candidate.id if request_candidate else "unknown"
                ),
            )

    def plan(self, context: AdapterContext) -> ExecutionPlan:
        issues = self.validate_input(context)
        blockers = tuple(issue for issue in issues if issue.severity.blocks_execution)
        if blockers:
            raise SystemBundleImportError(blockers[0].code, blockers[0].message)
        # Import is a pure normalization stage: all source files are already registered inputs.
        return ExecutionPlan(commands=(), expected_outputs=())

    def normalize_result(
        self,
        raw_outputs: dict[str, ArtifactRef],
        context: AdapterContext,
    ) -> SystemBuildResult:
        del raw_outputs
        request, complex_model, files = self._inputs(context)
        return import_charmm_gui_gromacs_bundle(
            request=request,
            complex_model=complex_model,
            bundle_files=files,
            adapter_version=self.version,
        )
