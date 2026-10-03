from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "validation"
    / "compare_gromacs_backend_reruns.py"
)
SPEC = importlib.util.spec_from_file_location("compare_gromacs_backend_reruns", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load GROMACS backend comparison script")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_cpu_minus_gpu_pairs_exact_times_and_converts_units(tmp_path: Path) -> None:
    cpu = tmp_path / "cpu.xvg"
    gpu = tmp_path / "gpu.xvg"
    header = '@ s0 legend "Potential"\n'
    cpu.write_text(header + "0 4.184\n100 8.368\n")
    gpu.write_text(header + "0 0\n100 4.184\n")

    rows = MODULE.compare_pair("fixture", "1", cpu, gpu, 100.0, 100.0)

    assert rows == [
        {
            "system": "fixture",
            "replica": "1",
            "time_ps": 100.0,
            "term": "Potential",
            "cpu_minus_gpu_kj_mol": 4.184,
            "cpu_minus_gpu_kcal_mol": 1.0,
        }
    ]


def test_rejects_misaligned_frames_and_energy_names(tmp_path: Path) -> None:
    cpu = tmp_path / "cpu.xvg"
    gpu = tmp_path / "gpu.xvg"
    cpu.write_text('@ s0 legend "Potential"\n0 1\n100 2\n')
    gpu.write_text('@ s0 legend "Potential"\n0 1\n101 2\n')

    with pytest.raises(ValueError, match="frame time mismatch"):
        MODULE.compare_pair("fixture", "1", cpu, gpu, 0.0, 100.0)

    gpu.write_text('@ s0 legend "Coulomb"\n0 1\n100 2\n')
    with pytest.raises(ValueError, match="term mismatch"):
        MODULE.compare_pair("fixture", "1", cpu, gpu, 0.0, 100.0)


def test_xvg_rejects_non_finite_values_and_invalid_time_order(tmp_path: Path) -> None:
    path = tmp_path / "bad.xvg"
    path.write_text('@ s0 legend "Potential"\n0 nan\n')
    with pytest.raises(ValueError, match="Non-finite"):
        MODULE.read_xvg(path)

    path.write_text('@ s0 legend "Potential"\n0 1\n0 2\n')
    with pytest.raises(ValueError, match="strictly increasing"):
        MODULE.read_xvg(path)


def test_named_backend_contrast_keeps_sign_and_labels(tmp_path: Path) -> None:
    gpu_cpu_pme = tmp_path / "gpu-cpu-pme.xvg"
    cpu_cpu_pme = tmp_path / "cpu-cpu-pme.xvg"
    header = '@ s0 legend "Coulomb (SR)"\n'
    gpu_cpu_pme.write_text(header + "0 0\n100 12.552\n")
    cpu_cpu_pme.write_text(header + "0 0\n100 8.368\n")

    rows = MODULE.compare_contrast(
        "fixture",
        "1",
        "GPU_NB_CPU_PME",
        gpu_cpu_pme,
        "CPU_NB_CPU_PME",
        cpu_cpu_pme,
        100.0,
        100.0,
    )

    assert rows[0]["first_backend"] == "GPU_NB_CPU_PME"
    assert rows[0]["second_backend"] == "CPU_NB_CPU_PME"
    assert rows[0]["first_minus_second_kcal_mol"] == pytest.approx(1.0)
