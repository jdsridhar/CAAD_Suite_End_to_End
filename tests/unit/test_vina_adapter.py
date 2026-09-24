"""Vina command planning and score parsing use archived golden docking outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caddsuite.adapters.docking.vina import (
    VinaOutputError,
    VinaParameters,
    ligand_efficiency,
    parse_vina_scores,
    plan_vina_command,
)
from caddsuite.contracts.structure import BindingSite, BindingSiteMethod, LigandReference
from caddsuite.domain.identity import new_ulid

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/data/golden/docking_g1"


def _site() -> BindingSite:
    return BindingSite(
        id=new_ulid(),
        target_id=new_ulid(),
        method=BindingSiteMethod.REFERENCE_LIGAND,
        reference=LigandReference(resname="8YZ", chain="A"),
        center_A=(4.701, 12.376, 188.797),
        size_A=(28.3, 22.0, 22.0),
        volume_A3=28.3 * 22.0 * 22.0,
    )


def test_vina_argv_uses_explicit_site_sampling_seed_and_per_job_cpu(tmp_path: Path) -> None:
    job = tmp_path / "job with spaces"
    job.mkdir()
    binary = job / "vina executable"
    receptor = job / "receptor.pdbqt"
    ligand = job / "ligand.pdbqt"
    for path in (binary, receptor, ligand):
        path.write_text("", encoding="utf-8")
    plan = plan_vina_command(
        executable=binary,
        receptor_pdbqt=receptor,
        ligand_pdbqt=ligand,
        site=_site(),
        output_pdbqt=job / "poses.pdbqt",
        log_file=job / "vina.log",
        parameters=VinaParameters(
            exhaustiveness=16,
            num_modes=9,
            energy_range_kcal_mol=3.0,
            cpu_cores=6,
            seed=42,
        ),
        working_directory=job,
    )
    assert plan.cwd == job.resolve()
    assert plan.argv[0] == str(binary.resolve())
    assert plan.argv[plan.argv.index("--center_x") + 1] == "4.701"
    assert plan.argv[plan.argv.index("--cpu") + 1] == "6"
    assert plan.argv[plan.argv.index("--seed") + 1] == "42"
    assert plan.argv[plan.argv.index("--out") + 1] == str((job / "poses.pdbqt").resolve())
    assert not any(";" in arg or "\n" in arg for arg in plan.argv)


@pytest.mark.parametrize("accession", ["RC8__5NIU", "RC34__5NIU"])
def test_golden_vina_pose_scores_and_ligand_efficiency(accession: str) -> None:
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    data = expected["ligands"][accession]
    output = (GOLDEN / "results" / f"{accession}_poses.pdbqt").read_text(encoding="utf-8")
    scores = parse_vina_scores(output, expected_modes=9)
    assert scores[0].affinity_kcal_mol == pytest.approx(data["score_kcal_mol"], abs=0.0005)
    assert scores[0].rank == 1
    assert ligand_efficiency(
        scores[0].affinity_kcal_mol,
        data["heavy_atoms"],
    ) == pytest.approx(data["ligand_efficiency_kcal_mol_per_heavy_atom"], abs=0.00005)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "REMARK VINA RESULT: invalid 0 0",
        "REMARK VINA RESULT: -8.0 -1 0",
        "REMARK VINA RESULT: -8.0 2.0 1.0",
        "REMARK VINA RESULT: nan 0 0",
    ],
)
def test_malformed_vina_score_output_fails_loudly(text: str) -> None:
    with pytest.raises(VinaOutputError):
        parse_vina_scores(text)


def test_vina_output_cannot_replace_an_input_file(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    binary, receptor, ligand = (job / name for name in ("vina", "rec.pdbqt", "lig.pdbqt"))
    for path in (binary, receptor, ligand):
        path.touch()
    with pytest.raises(ValueError, match="new files"):
        plan_vina_command(
            executable=binary,
            receptor_pdbqt=receptor,
            ligand_pdbqt=ligand,
            site=_site(),
            output_pdbqt=receptor,
            log_file=job / "vina.log",
            parameters=VinaParameters(
                exhaustiveness=1,
                num_modes=1,
                energy_range_kcal_mol=3,
                cpu_cores=1,
                seed=1,
            ),
            working_directory=job,
        )
