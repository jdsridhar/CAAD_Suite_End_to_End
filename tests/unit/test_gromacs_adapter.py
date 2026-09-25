"""GROMACS stage plans are safe, capability-checked, and explicit about resources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from caddsuite.adapters.md.gromacs import (
    GromacsMDAdapter,
    GromacsPlanError,
    GromacsStagePlanParameters,
    classify_grompp_warnings,
    normalize_index_final_newline,
    parse_gromacs_progress,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import (
    BoxSpec,
    ComponentForceField,
    ForceFieldComponent,
    ForceFieldFamily,
    MDProtocol,
    MDStage,
    MDStageInput,
    MDStageKind,
    MDSystem,
    Parameterization,
)
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import AdapterContext


def _ref(name: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=new_ulid(),
        role=name,
        sha256=hashlib.sha256(name.encode()).hexdigest(),
    )


def _software(name: str) -> SoftwareRef:
    return SoftwareRef(
        name=name,
        version="test",
        kind=SoftwareKind.ADAPTER,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )


def _result(*, profile: str = "caddsuite.charmm_gui.gromacs.charmm36m_cgenff_v1"):
    names = (
        "step3_input.gro",
        "step4.0_minimization.mdp",
        "step4.1_equilibration.mdp",
        "step5_production.mdp",
        "topol.top",
        "index.ndx",
    )
    refs = {name: _ref(name) for name in names}
    parameterization = Parameterization(
        id=new_ulid(),
        ff_family=ForceFieldFamily.CHARMM,
        protein_ff="CHARMM36m",
        ligand_method="CGenFF",
        ligand_charge_model="CGenFF",
        water_model="CHARMM TIP3P",
        ion_parameters="CHARMM ions",
        tool=_software("CHARMM-GUI"),
        compatibility_profile_id=profile,
        component_force_fields={
            ForceFieldComponent.PROTEIN: ComponentForceField(
                family=ForceFieldFamily.CHARMM, name="CHARMM36m"
            ),
            ForceFieldComponent.LIGAND: ComponentForceField(
                family=ForceFieldFamily.CHARMM, name="CGenFF"
            ),
            ForceFieldComponent.WATER: ComponentForceField(
                family=ForceFieldFamily.CHARMM, name="CHARMM TIP3P"
            ),
            ForceFieldComponent.IONS: ComponentForceField(
                family=ForceFieldFamily.CHARMM, name="CHARMM ions"
            ),
        },
        quality={"topology_format": "GROMACS"},
    )
    complex_id = new_ulid()
    system = MDSystem(
        id=new_ulid(),
        complex_id=complex_id,
        parameterization_id=parameterization.id,
        builder=_software("test builder"),
        box=BoxSpec(
            shape="rectangular", vectors_nm=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        ),
        n_atoms=10,
        net_charge=0.0,
        engine_inputs={"gromacs": refs},
    )
    protocol = MDProtocol(
        stages=(
            MDStage(kind=MDStageKind.MINIMIZATION, integrator="steep", n_steps=5000),
            MDStage(
                kind=MDStageKind.NPT,
                integrator="md",
                timestep_fs=1.0,
                n_steps=125000,
                temperature_K=303.15,
                pressure_bar=1.0,
                barostat="C-rescale",
            ),
            MDStage(
                kind=MDStageKind.PRODUCTION,
                integrator="md",
                timestep_fs=4.0,
                n_steps=250000,
                temperature_K=303.15,
            ),
        )
    )
    return SystemBuildResult(
        id=new_ulid(),
        request_id=new_ulid(),
        complex_id=complex_id,
        builder=system.builder,
        parameterization=parameterization,
        system=system,
        protocol=protocol,
        raw_artifacts=refs,
    )


def _context(
    tmp_path: Path,
    result: SystemBuildResult | None = None,
    **parameters: object,
) -> AdapterContext:
    build = result or _result()
    paths = cast(dict[str, object], parameters)
    artifacts = {
        "topology": build.system.engine_inputs["gromacs"][str(paths["topology_path"])],
    }
    if paths.get("resume_checkpoint_path") is not None:
        artifacts["tpr"] = _ref(f"{paths['output_prefix']}.tpr")
        artifacts["resume_checkpoint"] = _ref(str(paths["resume_checkpoint_path"]))
    else:
        mdp_path = str(paths["mdp_path"])
        coordinates_path = str(paths["coordinates_path"])
        artifacts["md_parameters"] = build.raw_artifacts.get(mdp_path, _ref(mdp_path))
        artifacts["coordinates"] = build.raw_artifacts.get(coordinates_path, _ref(coordinates_path))
        if paths.get("index_path") is not None:
            index_path = str(paths["index_path"])
            artifacts["index"] = build.raw_artifacts.get(index_path, _ref(index_path))
        if paths.get("reference_coordinates_path") is not None:
            reference_path = str(paths["reference_coordinates_path"])
            artifacts["reference_coordinates"] = build.raw_artifacts.get(
                reference_path, _ref(reference_path)
            )
        if paths.get("previous_checkpoint_path") is not None:
            checkpoint_path = str(paths["previous_checkpoint_path"])
            artifacts["previous_checkpoint"] = _ref(checkpoint_path)
    stage_input = MDStageInput(
        id=new_ulid(),
        system_id=build.system.id,
        stage_index=int(paths["stage_index"]),
        artifacts=artifacts,
    )
    return AdapterContext(
        inputs={"system_build": build, "stage_input": stage_input},
        parameters={"gromacs": parameters},
        working_directory=tmp_path,
    )


def _common(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "stage_index": 2,
        "mdp_path": "step5_production.mdp",
        "coordinates_path": "step4.1_equilibration.gro",
        "topology_path": "topol.top",
        "index_path": "index.ndx",
        "output_prefix": "step5_1",
        "target_ns": 100.0,
        "resource_mode": "gpu",
        "cpu_threads": 4,
        "gpu_ids": (0,),
    }
    values.update(overrides)
    return values


def test_gpu_production_plan_derives_segment_length_and_uses_argv(tmp_path: Path):
    adapter = GromacsMDAdapter()
    context = _context(tmp_path, **_common())

    assert adapter.validate_stage(context) == ()
    plan = adapter.plan_stage(context)

    assert plan.commands[0].argv == (
        "gmx",
        "grompp",
        "-f",
        "step5_production.mdp",
        "-o",
        "step5_1.tpr",
        "-c",
        "step4.1_equilibration.gro",
        "-p",
        "topol.top",
        "-n",
        "index.ndx",
    )
    assert "-maxwarn" not in plan.commands[0].argv
    assert plan.commands[1].argv == (
        "gmx",
        "mdrun",
        "-v",
        "-deffnm",
        "step5_1",
        "-ntomp",
        "4",
        "-pin",
        "on",
        "-pinoffset",
        "0",
        "-nb",
        "gpu",
        "-bonded",
        "gpu",
        "-pme",
        "gpu",
        "-update",
        "gpu",
    )
    assert plan.commands[1].environment == {
        "OMP_NUM_THREADS": "4",
        "CUDA_VISIBLE_DEVICES": "0",
        "OMP_WAIT_POLICY": "active",
    }
    assert plan.expected_outputs == ("step5_1.tpr", "step5_1.gro", "step5_1.log")


def test_minimization_uses_reference_and_optional_double_precision_executable(tmp_path: Path):
    adapter = GromacsMDAdapter()
    context = _context(
        tmp_path,
        stage_index=0,
        mdp_path="step4.0_minimization.mdp",
        coordinates_path="step3_input.gro",
        topology_path="topol.top",
        index_path="index.ndx",
        reference_coordinates_path="step3_input.gro",
        minimization_executable="gmx_d",
        output_prefix="step4.0_minimization",
        resource_mode="cpu",
        cpu_threads=2,
        gpu_ids=(),
    )

    plan = adapter.plan_stage(context)

    assert plan.commands[0].argv == (
        "gmx",
        "grompp",
        "-f",
        "step4.0_minimization.mdp",
        "-o",
        "step4.0_minimization.tpr",
        "-c",
        "step3_input.gro",
        "-p",
        "topol.top",
        "-r",
        "step3_input.gro",
        "-n",
        "index.ndx",
    )
    assert plan.commands[1].argv[:5] == (
        "gmx_d",
        "mdrun",
        "-v",
        "-deffnm",
        "step4.0_minimization",
    )


def _flag_values(argv: tuple[str, ...]) -> dict[str, str | None]:
    flags: dict[str, str | None] = {}
    no_value = {"-v", "-append"}
    cursor = 2
    while cursor < len(argv):
        flag = argv[cursor]
        if flag in no_value:
            flags[flag] = None
            cursor += 1
        else:
            flags[flag] = argv[cursor + 1]
            cursor += 2
    return flags


def test_legacy_min_eq_and_production_plan_matches_audited_command_golden(tmp_path: Path):
    golden_path = Path(__file__).parents[1] / "data/golden/md_gromacs_g1/legacy_plan.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    phases = golden["phases"]
    plans = {
        "minimization": _context(
            tmp_path,
            stage_index=0,
            mdp_path="step4.0_minimization.mdp",
            coordinates_path="step3_input.gro",
            topology_path="topol.top",
            index_path="index.ndx",
            reference_coordinates_path="step3_input.gro",
            output_prefix="step4.0_minimization",
            resource_mode="cpu",
            cpu_threads=1,
            gpu_ids=(),
        ),
        "equilibration": _context(
            tmp_path,
            stage_index=1,
            mdp_path="step4.1_equilibration.mdp",
            coordinates_path="step4.0_minimization.gro",
            topology_path="topol.top",
            index_path="index.ndx",
            reference_coordinates_path="step3_input.gro",
            output_prefix="step4.1_equilibration",
            resource_mode="gpu",
            cpu_threads=4,
            gpu_ids=(0,),
        ),
        "production_first_segment": _context(tmp_path, **_common()),
        "production_continuation": _context(
            tmp_path,
            **_common(
                coordinates_path="step5_1.gro",
                output_prefix="step5_2",
                segment_index=2,
                previous_checkpoint_path="step5_1.cpt",
            ),
        ),
    }

    for phase, context in plans.items():
        actual = GromacsMDAdapter().plan_stage(context)
        legacy_grompp = tuple(phases[phase]["grompp"])
        legacy_grompp = tuple(
            legacy_grompp[index]
            for index in range(len(legacy_grompp))
            if legacy_grompp[index] != "-maxwarn"
            and not (index > 0 and legacy_grompp[index - 1] == "-maxwarn")
        )
        if phase == "production_continuation":
            legacy_grompp = tuple(
                token.replace("<previous>", "1").replace("<segment>", "2")
                for token in legacy_grompp
            )
        assert actual.commands[0].argv[:2] == legacy_grompp[:2]
        assert _flag_values(actual.commands[0].argv) == _flag_values(legacy_grompp)

        legacy_mdrun = tuple(phases[phase]["mdrun"])
        if phase == "production_continuation":
            legacy_mdrun = tuple(token.replace("<segment>", "2") for token in legacy_mdrun)
        actual_mdrun_flags = _flag_values(actual.commands[1].argv)
        legacy_mdrun_flags = _flag_values(legacy_mdrun)
        assert actual.commands[1].argv[:2] == legacy_mdrun[:2]
        assert all(
            actual_mdrun_flags.get(key) == value for key, value in legacy_mdrun_flags.items()
        )


def test_equilibration_plan_preserves_original_restraint_reference(tmp_path: Path):
    adapter = GromacsMDAdapter()
    context = _context(
        tmp_path,
        stage_index=1,
        mdp_path="step4.1_equilibration.mdp",
        coordinates_path="step4.0_minimization.gro",
        topology_path="topol.top",
        index_path="index.ndx",
        reference_coordinates_path="step3_input.gro",
        output_prefix="step4.1_equilibration",
        resource_mode="gpu",
        cpu_threads=4,
        gpu_ids=(0,),
    )

    plan = adapter.plan_stage(context)

    assert "-c" in plan.commands[0].argv
    assert (
        plan.commands[0].argv[plan.commands[0].argv.index("-c") + 1] == "step4.0_minimization.gro"
    )
    assert plan.commands[0].argv[plan.commands[0].argv.index("-r") + 1] == "step3_input.gro"


def test_production_continuation_and_interrupted_segment_resume_are_explicit(tmp_path: Path):
    adapter = GromacsMDAdapter()
    continuation = adapter.plan_stage(
        _context(
            tmp_path,
            **_common(
                coordinates_path="step5_1.gro",
                output_prefix="step5_2",
                segment_index=2,
                previous_checkpoint_path="step5_1.cpt",
            ),
        )
    )
    assert continuation.commands[0].argv[-2:] == ("-t", "step5_1.cpt")

    resume = adapter.plan_stage(
        _context(
            tmp_path,
            **_common(
                output_prefix="step5_2",
                segment_index=2,
                coordinates_path="step5_1.gro",
                previous_checkpoint_path="step5_1.cpt",
                resume_checkpoint_path="step5_2.cpt",
            ),
        )
    )
    assert len(resume.commands) == 1
    assert resume.commands[0].argv[1:] == (
        "mdrun",
        "-v",
        "-deffnm",
        "step5_2",
        "-cpi",
        "step5_2.cpt",
        "-append",
        "-ntomp",
        "4",
        "-pin",
        "on",
        "-pinoffset",
        "0",
        "-nb",
        "gpu",
        "-bonded",
        "gpu",
        "-pme",
        "gpu",
        "-update",
        "gpu",
    )


def test_gromacs_checkpoint_interval_and_runtime_limit_are_explicit(tmp_path: Path):
    plan = GromacsMDAdapter().plan_stage(
        _context(
            tmp_path,
            **_common(checkpoint_interval_minutes=0.01, maximum_runtime_hours=0.00005),
        )
    )

    argv = plan.commands[1].argv
    assert argv[argv.index("-cpt") + 1] == "0.01"
    assert argv[argv.index("-maxh") + 1] == "5e-05"


def test_bad_duration_checkpoint_profile_and_paths_block_execution(tmp_path: Path):
    adapter = GromacsMDAdapter()
    not_multiple = _context(tmp_path, **_common(target_ns=1.5))
    assert adapter.validate_stage(not_multiple)[0].code == "MD.GROMACS_TARGET_NOT_SEGMENT_MULTIPLE"
    with pytest.raises(GromacsPlanError, match="integer multiple"):
        adapter.plan_stage(not_multiple)

    no_checkpoint = _context(
        tmp_path,
        **_common(segment_index=2, coordinates_path="step5_1.gro", output_prefix="step5_2"),
    )
    assert adapter.validate_stage(no_checkpoint)[0].code == "MD.GROMACS_CHECKPOINT_MISSING"

    disabled_profile = _context(
        tmp_path,
        _result(profile="caddsuite.ambertools.gromacs.ff14sb_gaff2_tip3p_v1"),
        **_common(),
    )
    assert (
        adapter.validate_stage(disabled_profile)[0].code
        == "MD.GROMACS_FORCE_FIELD_PROFILE_UNSUPPORTED"
    )

    with pytest.raises(ValidationError, match="canonical relative path"):
        GromacsStagePlanParameters.model_validate(
            {**_common(), "coordinates_path": "../../outside.gro"}
        )


def test_stage_input_requires_hashed_artifacts_and_matching_system_lineage(tmp_path: Path):
    adapter = GromacsMDAdapter()
    context = _context(tmp_path, **_common())
    build = cast(SystemBuildResult, context.inputs["system_build"])
    stage_input = cast(MDStageInput, context.inputs["stage_input"])
    with pytest.raises(ValidationError, match="must be hashed"):
        MDStageInput(
            id=new_ulid(),
            system_id=build.system.id,
            stage_index=2,
            artifacts={"topology": ArtifactRef(artifact_id=new_ulid(), role="topology")},
        )

    missing_role = MDStageInput(
        id=new_ulid(),
        system_id=build.system.id,
        stage_index=2,
        artifacts={"topology": stage_input.artifacts["topology"]},
    )
    missing_context = AdapterContext(
        inputs={"system_build": build, "stage_input": missing_role},
        parameters=context.parameters,
        working_directory=tmp_path,
    )
    assert adapter.validate_stage(missing_context)[0].code == "MD.GROMACS_STAGE_ARTIFACT_MISSING"

    tampered_roles = dict(stage_input.artifacts)
    tampered_roles["topology"] = _ref("different topology")
    mismatched = MDStageInput(
        id=new_ulid(),
        system_id=build.system.id,
        stage_index=2,
        artifacts=tampered_roles,
    )
    mismatched_context = AdapterContext(
        inputs={"system_build": build, "stage_input": mismatched},
        parameters=context.parameters,
        working_directory=tmp_path,
    )
    assert (
        adapter.validate_stage(mismatched_context)[0].code
        == "MD.GROMACS_STAGE_ARTIFACT_HASH_MISMATCH"
    )


def test_index_newline_normalization_is_append_only_and_idempotent():
    original = b"[ Protein ]\r\n1 2 3\r\n[ LIG ]\r\n4 5"

    normalized, changed = normalize_index_final_newline(original)
    repeated, changed_again = normalize_index_final_newline(normalized)

    assert changed
    assert normalized == original + b"\n"
    assert normalized[:-1] == original
    assert not changed_again
    assert repeated == normalized

    already_normalized, already_changed = normalize_index_final_newline(b"[ LIG ]\n1 2\n")
    assert not already_changed
    assert already_normalized == b"[ LIG ]\n1 2\n"


def test_gromacs_adapter_maps_hash_linked_stage_artifacts_to_safe_paths(tmp_path: Path) -> None:
    params = _common(resource_mode="cpu", gpu_ids=())
    context = _context(tmp_path, **params)
    adapter = GromacsMDAdapter()
    mapped = adapter.stage_input_artifacts(context)
    stage_input = context.inputs["stage_input"]
    assert isinstance(stage_input, MDStageInput)
    assert mapped[params["topology_path"]] == stage_input.artifacts["topology"]
    assert mapped[params["mdp_path"]] == stage_input.artifacts["md_parameters"]
    assert mapped[params["coordinates_path"]] == stage_input.artifacts["coordinates"]


def test_grompp_warning_classifier_separates_index_warning_from_notes_and_other_warnings(
    tmp_path: Path,
):
    index_issues = classify_grompp_warnings(
        b"Warning: file does not end with a newline, last line:\n49681 49682 \n"
        b"NOTE 1 [file run.mdp]: this note is not a warning\n",
        b"",
    )
    assert len(index_issues) == 1
    assert index_issues[0].code == "MD.GROMACS_INDEX_FINAL_NEWLINE"
    assert index_issues[0].severity.value == "blocker"
    assert "49681 49682" in index_issues[0].evidence["warning"]

    generic_issues = classify_grompp_warnings(
        "",
        b"WARNING 1 [file system.top, line 22]:\n  Atom type mismatch detected\n\n"
        b"NOTE 2 [file run.mdp]: informational only\n",
    )
    assert len(generic_issues) == 1
    assert generic_issues[0].code == "MD.GROMACS_WARNING_BLOCKED"
    assert "Atom type mismatch" in generic_issues[0].message
    assert classify_grompp_warnings("NOTE 1 [file run.mdp]: no warning", "") == ()

    adapter = GromacsMDAdapter()
    context = _context(tmp_path, **_common())
    execution_issues = adapter.validate_execution_step(
        context, 0, b"", b"WARNING 1 [file system.top, line 22]:\n  Atom type mismatch detected\n"
    )
    assert len(execution_issues) == 1
    assert execution_issues[0].code == "MD.GROMACS_WARNING_BLOCKED"
    assert (
        adapter.validate_execution_step(context, 1, b"", b"WARNING 1 ignored by grompp only\n")
        == ()
    )


def test_gromacs_progress_parses_carriage_returns_and_both_eta_formats():
    progress = parse_gromacs_progress(
        b"step 100, will finish Thu Sep 24 12:30:00 2026\r"
        b"step 250, remaining wall clock time: 43 s\r",
        total_steps=1000,
    )

    assert progress is not None
    assert progress.completed_steps == 250
    assert progress.fraction_completed == pytest.approx(0.25)
    assert progress.estimated_remaining_seconds == 43.0
    assert progress.estimated_finish_text is None
    assert progress.source == "stage_log"

    finish = parse_gromacs_progress(
        "step 875, will finish Thu Sep 24 12:30:00 2026\r", total_steps=1000
    )
    assert finish is not None
    assert finish.fraction_completed == pytest.approx(0.875)
    assert finish.estimated_finish_text == "Thu Sep 24 12:30:00 2026"
    assert finish.estimated_remaining_seconds is None

    fixture = (
        (Path(__file__).parents[1] / "data/golden/md_gromacs_g1/progress_formats.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    captured_finish = parse_gromacs_progress(fixture[0], total_steps=250_000)
    captured_remaining = parse_gromacs_progress(fixture[1], total_steps=250_000)
    captured_complete = parse_gromacs_progress(fixture[2], total_steps=250_000)
    assert captured_finish is not None
    assert captured_finish.estimated_finish_text == "Thu Sep 10 11:09:04 2026"
    assert captured_remaining is not None
    assert captured_remaining.estimated_remaining_seconds == 127.0
    assert captured_complete is not None
    assert captured_complete.fraction_completed == 1.0
    assert captured_complete.estimated_remaining_seconds == 0.0


def test_gromacs_progress_falls_back_to_aggregate_log_and_rejects_invalid_values():
    progress = parse_gromacs_progress(
        "GROMACS is preparing the run",
        total_steps=500,
        aggregate_log=b"old output\rstep 125, remaining wall clock time: 20 s\r",
    )
    assert progress is not None
    assert progress.completed_steps == 125
    assert progress.source == "aggregate_log"
    assert (
        parse_gromacs_progress("step 900, remaining wall clock time: 2 s", total_steps=800) is None
    )
    assert parse_gromacs_progress("no progress yet", total_steps=800) is None
    with pytest.raises(ValueError, match="total_steps"):
        parse_gromacs_progress("", total_steps=0)


def test_missing_system_build_is_reported_as_structured_validation(tmp_path: Path):
    adapter = GromacsMDAdapter()
    context = AdapterContext(inputs={}, parameters={"gromacs": {}}, working_directory=tmp_path)

    issues = adapter.validate_stage(context)

    assert len(issues) == 1
    assert issues[0].code == "MD.GROMACS_CONTEXT_INVALID"
    assert issues[0].severity.value == "blocker"
