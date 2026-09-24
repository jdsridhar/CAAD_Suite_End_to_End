"""Synthetic checks for safe CHARMM-GUI GROMACS bundle normalization."""

from __future__ import annotations

import hashlib

import pytest

from caddsuite.adapters.system_builders.charmm_gui_import import (
    SystemBundleImportError,
    import_charmm_gui_gromacs_bundle,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildRequest
from caddsuite.domain.identity import new_ulid


def _atom(resid: int, residue: str, name: str, index: int) -> str:
    return f"{resid:5d}{residue:<5.5s}{name:>5.5s}{index:5d}{index / 10:8.3f}{0.0:8.3f}{0.0:8.3f}"


def _bundle() -> dict[str, bytes]:
    gro = "\n".join(
        [
            "synthetic test system",
            "4",
            _atom(1, "ALA", "N", 1),
            _atom(1, "ALA", "H", 2),
            _atom(2, "LIG", "C1", 3),
            _atom(2, "LIG", "H1", 4),
            "2.00000 2.00000 2.00000",
        ]
    )
    return {
        "topol.top": b"""#include "toppar/forcefield.itp"
#include "toppar/PROA.itp"
#include "toppar/LIG.itp"
[ system ]
synthetic
[ molecules ]
PROA 1
LIG 1
""",
        "step3_input.gro": gro.encode(),
        "index.ndx": b"[ Protein ]\n1 2\n[ LIG ]\n3 4\n",
        "step4.0_minimization.mdp": b"integrator = steep\nnsteps = 5000\ndefine = -DPOSRES\n",
        "step4.1_equilibration.mdp": (
            b"integrator = md\ndt = 0.001\nnsteps = 125000\n"
            b"tcoupl = v-rescale\nref_t = 303.15 303.15\nconstraints = h-bonds\n"
        ),
        "step5_production.mdp": (
            b"integrator = md\ndt = 0.004\nnsteps = 250000\n"
            b"tcoupl = v-rescale\nref_t = 303.15 303.15\n"
            b"pcoupl = C-rescale\nref_p = 1.0\nconstraints = h-bonds\n"
            b"coulombtype = PME\nvdw-modifier = Force-switch\n"
        ),
        "toppar/forcefield.itp": b"""; CHARMM FF in GROMACS format
[ defaults ]
1 2 yes 1.0 1.0
""",
        "toppar/PROA.itp": b"""[ moleculetype ]
PROA 3
[ atoms ]
1 NT 1 ALA N 1 -0.3 14.0
2 HT 1 ALA H 1 0.3 1.0
""",
        "toppar/LIG.itp": b"""[ moleculetype ]
LIG 3
[ atoms ]
1 CT 1 LIG C1 1 0.0 12.0
2 HT 1 LIG H1 1 0.0 1.0
""",
    }


def _inputs(files: dict[str, bytes], *, ligand_atoms: int = 2):
    refs = {
        path: ArtifactRef(
            artifact_id=new_ulid(),
            role=f"bundle_file:{path}",
            sha256=hashlib.sha256(data).hexdigest(),
        )
        for path, data in files.items()
    }
    complex_model = Complex(
        id=new_ulid(),
        compound_id=new_ulid(),
        form_id=new_ulid(),
        target_id=new_ulid(),
        structure_id=new_ulid(),
        prepared_receptor_id=new_ulid(),
        docking_run_id=new_ulid(),
        pose_id=new_ulid(),
        protein=ArtifactRef(artifact_id=new_ulid(), role="protein"),
        ligand=ArtifactRef(artifact_id=new_ulid(), role="ligand"),
        assembled=ArtifactRef(artifact_id=new_ulid(), role="assembled"),
        protein_atom_count=2,
        ligand_atom_count=ligand_atoms,
        ligand_heavy_atom_count=1,
        coordinate_fidelity_max_dev_A=0.0,
    )
    request = SystemBuildRequest(
        id=new_ulid(),
        complex_id=complex_model.id,
        compound_id=complex_model.compound_id,
        form_id=complex_model.form_id,
        target_id=complex_model.target_id,
        pose_id=complex_model.pose_id,
        source_artifacts=refs,
        selections={"ligand": "LIG", "protein": "Protein"},
        mode="import",
        parameters={
            "ff_family": "charmm",
            "protein_ff": "CHARMM36m",
            "ligand_method": "CGenFF",
            "ligand_charge_model": "CGenFF",
            "water_model": "CHARMM TIP3P",
            "ion_parameters": "CHARMM ions",
            "ligand_resnames": ["LIG"],
            "ligand_molecule_types": ["LIG"],
            "protein_molecule_types": ["PROA"],
            "selection_index_path": "index.ndx",
        },
    )
    return request, complex_model


def test_importer_normalizes_counts_selection_box_and_protocol():
    files = _bundle()
    request, complex_model = _inputs(files)
    result = import_charmm_gui_gromacs_bundle(
        request=request, complex_model=complex_model, bundle_files=files
    )
    assert result.system.n_atoms == 4
    assert result.system.composition == {"PROA": 1, "LIG": 1}
    assert result.system.selections["ligand"].n_atoms == 2
    assert result.system.selections["ligand"].verified
    assert result.system.box.shape == "rectangular"
    assert result.parameterization.ff_family.value == "charmm"
    assert result.protocol.stages[0].kind.value == "minimization"
    assert result.protocol.stages[1].timestep_fs == pytest.approx(1.0)
    assert result.protocol.stages[1].length_ns == pytest.approx(0.125)
    assert result.protocol.stages[2].kind.value == "production"
    assert result.protocol.stages[2].timestep_fs == pytest.approx(4.0)
    assert result.protocol.stages[2].length_ns == pytest.approx(1.0)
    assert result.protocol.stages[2].pressure_bar == pytest.approx(1.0)
    assert result.protocol.stages[2].barostat == "C-rescale"
    assert result.protocol.stages[2].hmr is None
    assert result.validation_issues[0].code == "MD.HMR_UNVERIFIED"
    assert set(result.raw_artifacts) == set(files)


def test_importer_rejects_hash_tampering_before_normalization():
    files = _bundle()
    request, complex_model = _inputs(files)
    files["step3_input.gro"] += b"tamper"
    with pytest.raises(SystemBundleImportError, match="digest") as exc:
        import_charmm_gui_gromacs_bundle(
            request=request, complex_model=complex_model, bundle_files=files
        )
    assert exc.value.code == "SYSTEM_BUNDLE.HASH_MISMATCH"


def test_importer_rejects_ligand_group_that_disagrees_with_gro():
    files = _bundle()
    files["index.ndx"] = b"[ Protein ]\n1 2\n[ LIG ]\n2 4\n"
    request, complex_model = _inputs(files)
    with pytest.raises(SystemBundleImportError, match="residue"):
        import_charmm_gui_gromacs_bundle(
            request=request, complex_model=complex_model, bundle_files=files
        )


def test_importer_rejects_missing_includes_and_path_traversal():
    files = _bundle()
    files["topol.top"] = files["topol.top"].replace(b"toppar/LIG.itp", b"toppar/missing.itp")
    request, complex_model = _inputs(files)
    with pytest.raises(SystemBundleImportError) as exc:
        import_charmm_gui_gromacs_bundle(
            request=request, complex_model=complex_model, bundle_files=files
        )
    assert exc.value.code == "SYSTEM_BUNDLE.MISSING_INCLUDE"

    unsafe = dict(files)
    unsafe["../outside"] = b"x"
    request, complex_model = _inputs(unsafe)
    with pytest.raises(SystemBundleImportError) as exc:
        import_charmm_gui_gromacs_bundle(
            request=request, complex_model=complex_model, bundle_files=unsafe
        )
    assert exc.value.code == "SYSTEM_BUNDLE.UNSAFE_PATH"


def test_importer_requires_complex_lineage_and_explicit_compatible_method():
    files = _bundle()
    request, complex_model = _inputs(files)
    wrong_lineage = request.model_copy(update={"form_id": new_ulid()})
    with pytest.raises(SystemBundleImportError) as exc:
        import_charmm_gui_gromacs_bundle(
            request=wrong_lineage, complex_model=complex_model, bundle_files=files
        )
    assert exc.value.code == "SYSTEM_BUNDLE.LINEAGE_MISMATCH"

    wrong_forcefield = request.model_copy(
        update={"parameters": {**request.parameters, "ff_family": "amber"}}
    )
    with pytest.raises(SystemBundleImportError) as exc:
        import_charmm_gui_gromacs_bundle(
            request=wrong_forcefield, complex_model=complex_model, bundle_files=files
        )
    assert exc.value.code == "SYSTEM_BUNDLE.FORCEFIELD_MISMATCH"


def test_importer_decodes_gro_triclinic_box_component_order():
    files = _bundle()
    files["step3_input.gro"] = files["step3_input.gro"].replace(
        b"2.00000 2.00000 2.00000", b"2.0 2.1 2.2 0.0 0.0 0.3 0.0 0.4 0.5"
    )
    request, complex_model = _inputs(files)
    result = import_charmm_gui_gromacs_bundle(
        request=request, complex_model=complex_model, bundle_files=files
    )
    assert result.system.box.shape == "triclinic"
    assert result.system.box.vectors_nm == (
        (2.0, 0.0, 0.0),
        (0.3, 2.1, 0.0),
        (0.4, 0.5, 2.2),
    )


def test_importer_rejects_unsupported_gro_triclinic_form():
    files = _bundle()
    files["step3_input.gro"] = files["step3_input.gro"].replace(
        b"2.00000 2.00000 2.00000", b"2.0 2.1 2.2 0.1 0.0 0.3 0.0 0.4 0.5"
    )
    request, complex_model = _inputs(files)
    with pytest.raises(SystemBundleImportError) as exc:
        import_charmm_gui_gromacs_bundle(
            request=request, complex_model=complex_model, bundle_files=files
        )
    assert exc.value.code == "SYSTEM_BUNDLE.GRO_BOX_INVALID"
