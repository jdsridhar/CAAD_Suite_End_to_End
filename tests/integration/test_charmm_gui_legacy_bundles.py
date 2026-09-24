"""Read-only regression checks against the user's prepared CHARMM-GUI bundles.

Set CADDSUITE_MDSUITE_DATA to the mdsuite_data directory to enable this check.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from caddsuite.adapters.system_builders.charmm_gui_import import (
    CharmmGuiGromacsImportAdapter,
)
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildRequest
from caddsuite.domain.identity import new_ulid
from caddsuite.plugins.registry import adapter_conformance_issues
from caddsuite.ports.adapters import AdapterContext

DATA_ROOT = os.environ.get("CADDSUITE_MDSUITE_DATA")
pytestmark = [
    pytest.mark.legacy_data,
    pytest.mark.skipif(
        not DATA_ROOT, reason="set CADDSUITE_MDSUITE_DATA for read-only legacy data"
    ),
]
CASES = {
    "2M2D_LIG": (48, ("PROA",), 49682),
    "2M2D_STD": (56, ("PROA",), 48177),
    "5NIU_LIG": (51, ("PROA", "PROB"), 51792),
    "5NIU_STD": (68, ("PROA", "PROB"), 51794),
}


def _index_groups(payload: bytes) -> dict[str, tuple[int, ...]]:
    groups: dict[str, list[int]] = {}
    current: str | None = None
    for line in payload.decode().splitlines():
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            groups[current] = []
        else:
            assert current is not None
            groups[current].extend(int(value) for value in line.split())
    return {name: tuple(indices) for name, indices in groups.items()}


def test_charmm_gui_real_bundles_normalize_without_modifying_source(tmp_path: Path):
    data_root = Path(DATA_ROOT or ".").resolve()
    projects_root = data_root / "projects" if (data_root / "projects").is_dir() else data_root
    observed: dict[str, tuple[int, tuple[float | None, ...]]] = {}

    for project, (expected_ligand_atoms, protein_types, expected_total_atoms) in CASES.items():
        bundle_root = (projects_root / project / "gromacs").resolve(strict=True)
        paths = [
            "topol.top",
            "step3_input.gro",
            "index.ndx",
            "analysis/analysis.ndx",
            "step4.0_minimization.mdp",
            "step4.1_equilibration.mdp",
            "step5_production.mdp",
        ]
        paths.extend(
            path.relative_to(bundle_root).as_posix()
            for path in sorted((bundle_root / "toppar").rglob("*"))
            if path.is_file() and ":Zone.Identifier" not in path.name
        )
        files: dict[str, bytes] = {}
        for relative in paths:
            source = (bundle_root / relative).resolve(strict=True)
            source.relative_to(bundle_root)
            assert source.is_file()
            files[relative] = source.read_bytes()

        refs = {
            path: ArtifactRef(
                artifact_id=new_ulid(),
                role=f"bundle_file:{path}",
                sha256=hashlib.sha256(payload).hexdigest(),
            )
            for path, payload in files.items()
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
            assembled=ArtifactRef(artifact_id=new_ulid(), role="complex"),
            protein_atom_count=1,
            ligand_atom_count=expected_ligand_atoms,
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
                "protein_molecule_types": list(protein_types),
                "selection_index_path": "analysis/analysis.ndx",
            },
        )
        stage_dir = tmp_path / project
        for relative, payload in files.items():
            destination = stage_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        context = AdapterContext(
            inputs={"request": request, "complex": complex_model},
            parameters={},
            working_directory=stage_dir,
        )
        adapter = CharmmGuiGromacsImportAdapter()
        assert adapter_conformance_issues(adapter) == ()
        assert [issue.code for issue in adapter.validate_input(context)] == ["MD.HMR_UNVERIFIED"]
        assert adapter.plan(context).commands == ()
        result = adapter.normalize_result({}, context)
        assert result.system.n_atoms == expected_total_atoms
        assert result.system.selections["ligand"].n_atoms == expected_ligand_atoms
        assert result.system.selections["ligand"].verified
        assert result.system.selections["protein"].verified
        assert result.parameterization.ff_family.value == "charmm"
        assert result.system.selections["protein"].n_atoms == len(
            _index_groups(files["analysis/analysis.ndx"])["Protein"]
        )
        if project == "5NIU_STD":
            analysis_groups = _index_groups(files["analysis/analysis.ndx"])
            assert list(analysis_groups)[1] == "Protein"
            assert set(protein_types) == {"PROA", "PROB"}
        assert len(result.protocol.stages) == 3
        observed[project] = (
            expected_ligand_atoms,
            tuple(s.length_ns for s in result.protocol.stages),
        )

    assert set(observed) == set(CASES)
    assert all(values[1] == (None, 0.125, 1.0) for values in observed.values())
