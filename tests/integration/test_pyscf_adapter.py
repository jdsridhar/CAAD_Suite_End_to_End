"""PySCF adapter planning and real-engine compatibility proof."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from caddsuite.adapters.qm.pyscf import PySCFAdapterParameters, PySCFQMAdapter
from caddsuite.contracts.base import ArtifactRef, EntityRef, SoftwareRef
from caddsuite.contracts.qm import QMCalculation, QMModel, QMProtocol
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind, Conformer
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid

ROOT = Path(__file__).resolve().parents[2]
PYSCF_PYTHON = os.environ.get("CADDSUITE_PYSCF_PYTHON")


def _case(tmp_path: Path, python: str) -> tuple[object, ...]:
    Chem = pytest.importorskip("rdkit.Chem")
    AllChem = pytest.importorskip("rdkit.Chem.AllChem")
    compound_id = new_ulid()
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    molecule = Chem.AddHs(Chem.MolFromSmiles(form.smiles))
    assert AllChem.EmbedMolecule(molecule, randomSeed=4815) == 0
    sdf = tmp_path / "ethanol.sdf"
    writer = Chem.SDWriter(str(sdf))
    writer.write(molecule)
    writer.close()
    structure = ArtifactRef(
        artifact_id=new_ulid(),
        role="conformer_structure",
        sha256=hashlib.sha256(sdf.read_bytes()).hexdigest(),
    )
    conformer = Conformer(
        id=new_ulid(),
        form_id=form.id,
        compound_id=compound_id,
        generator="ETKDGv3",
        seed=4815,
        structure=structure,
    )
    calculation = QMCalculation(
        id=new_ulid(),
        accession="CMP0001_QM_001",
        form_id=form.id,
        geometry_source=EntityRef(kind="conformer", id=conformer.id),
        engine=SoftwareRef(
            name="PySCF",
            version="unknown",
            kind=SoftwareKind.ENGINE,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
        adapter=SoftwareRef(
            name="caddsuite.qm.pyscf",
            version="0.1.0",
            kind=SoftwareKind.ADAPTER,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        ),
        model=QMModel(method="b3lyp", basis="6-31g*"),
        protocol=QMProtocol.SINGLE_POINT,
        charge=0,
        multiplicity=1,
        requested_properties=("total_energy_Eh", "orbitals", "dipole_D"),
    )
    params = PySCFAdapterParameters(
        python_executable=python,
        worker_source_directory=str(ROOT / "src"),
        memory_mb=2000,
        max_cycle=100,
        timeout_seconds=300,
    ).model_dump()
    return (
        calculation,
        {"form": form, "conformer": conformer},
        {str(structure.artifact_id): sdf},
        params,
        sdf,
    )


def test_adapter_exposes_only_validated_molecular_single_point_capabilities(tmp_path: Path) -> None:
    python = PYSCF_PYTHON or sys.executable
    calculation, inputs, files, params, _ = _case(tmp_path, python)
    adapter = PySCFQMAdapter()
    issues = adapter.validate_calculation(
        calculation,
        parameters=params,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    assert not issues
    assert adapter.capabilities.protocols == (QMProtocol.SINGLE_POINT,)
    assert adapter.capabilities.supports_molecular_systems
    assert not adapter.capabilities.supports_periodic_systems


@pytest.mark.engine("PySCF")
@pytest.mark.slow
@pytest.mark.skipif(
    not PYSCF_PYTHON, reason="set CADDSUITE_PYSCF_PYTHON to the PySCF environment interpreter"
)
def test_real_pyscf_worker_normalizes_to_the_shared_qm_result(tmp_path: Path) -> None:
    assert PYSCF_PYTHON is not None
    calculation, inputs, files, params, _ = _case(tmp_path, PYSCF_PYTHON)
    adapter = PySCFQMAdapter()
    assert (
        adapter.validate_calculation(
            calculation,
            parameters=params,
            input_contracts=inputs,
            staged_inputs=files,
            working_directory=tmp_path,
        )
        == ()
    )
    plan = adapter.plan_calculation(
        calculation,
        parameters=params,
        input_contracts=inputs,
        staged_inputs=files,
        working_directory=tmp_path,
    )
    (tmp_path / plan.task_filename).write_text(
        json.dumps(plan.task_request, allow_nan=False), encoding="utf-8"
    )
    step = plan.execution.commands[0]
    completed = subprocess.run(
        step.argv,
        cwd=step.working_directory,
        env={**os.environ, **step.environment},
        capture_output=True,
        text=True,
        timeout=plan.timeout_seconds,
        check=False,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    envelope = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    geometry_file = tmp_path / "pyscf_final_geometry.xyz"
    geometry_artifact = ArtifactRef(
        artifact_id=new_ulid(),
        role="final_geometry",
        sha256=hashlib.sha256(geometry_file.read_bytes()).hexdigest(),
    )
    normalized = adapter.normalize_result(
        calculation,
        envelope,
        output_artifacts={"final_geometry": geometry_artifact},
    )
    assert normalized.total_energy_Eh < 0.0
    assert normalized.convergence.scf_converged
    assert normalized.orbitals is not None
    assert normalized.orbitals.gap_eV > 0.0
    assert normalized.dipole_D is not None
    assert normalized.dipole_D > 0.0
    assert normalized.final_geometry == geometry_artifact
    assert envelope["result"]["parameters"]["solvent"] is None
