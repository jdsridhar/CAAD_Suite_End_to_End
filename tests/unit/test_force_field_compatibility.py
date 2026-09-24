"""Force-field profiles distinguish supported combinations from unreviewed mixtures."""

from __future__ import annotations

from caddsuite.contracts.base import SoftwareRef
from caddsuite.contracts.md import (
    BoxSpec,
    ComponentForceField,
    ForceFieldComponent,
    ForceFieldFamily,
    MDSystem,
    Parameterization,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.validation import Severity, default_registry
from caddsuite.validation.force_field_profiles import (
    CHARMM_GUI_GROMACS_PROFILE_ID,
    ForceFieldCompatibilityRegistry,
    default_force_field_profiles,
)


def _parameterization() -> Parameterization:
    return Parameterization(
        id=new_ulid(),
        ff_family=ForceFieldFamily.CHARMM,
        protein_ff="CHARMM36m",
        ligand_method="CGenFF",
        ligand_charge_model="CGenFF",
        water_model="CHARMM TIP3P",
        ion_parameters="CHARMM ions",
        tool=SoftwareRef(
            name="CHARMM-GUI",
            version="not recorded",
            kind=SoftwareKind.MANUAL_STEP,
            license_class=LicenseClass.ACADEMIC_NONCOMMERCIAL,
        ),
        compatibility_profile_id=CHARMM_GUI_GROMACS_PROFILE_ID,
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


def _system(parameterization: Parameterization) -> MDSystem:
    builder = SoftwareRef(
        name="test-importer",
        version="1.0",
        kind=SoftwareKind.ADAPTER,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )
    return MDSystem(
        id=new_ulid(),
        parameterization_id=parameterization.id,
        builder=builder,
        box=BoxSpec(
            shape="rectangular",
            vectors_nm=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ),
        n_atoms=4,
        net_charge=0.0,
        engine_inputs={"gromacs": {}},
    )


def _check(parameterization: Parameterization, profiles=None):
    context = {"parameterization": parameterization, "md_system": _system(parameterization)}
    if profiles is not None:
        context["force_field_profiles"] = profiles
    return default_registry().run("system_build", context)


def test_audited_charmm_profile_matches_explicit_component_families():
    assert _check(_parameterization()) == []


def test_unregistered_or_absent_profile_requires_scientific_review():
    parameterization = _parameterization().model_copy(update={"compatibility_profile_id": None})
    issues = _check(parameterization)
    assert [(issue.code, issue.severity) for issue in issues] == [
        ("FF.FAMILY_CONSISTENCY", Severity.DECISION_REQUIRED)
    ]


def test_declarations_that_contradict_selected_profile_block_execution():
    parameterization = _parameterization()
    components = dict(parameterization.component_force_fields)
    components[ForceFieldComponent.LIGAND] = ComponentForceField(
        family=ForceFieldFamily.AMBER, name="GAFF2"
    )
    parameterization = parameterization.model_copy(update={"component_force_fields": components})
    issues = _check(parameterization)
    assert [(issue.code, issue.severity) for issue in issues] == [
        ("FF.FAMILY_CONSISTENCY", Severity.BLOCKER)
    ]
    assert "ligand" in issues[0].evidence["mismatches"]


def test_registered_but_disabled_profile_requires_review():
    disabled = default_force_field_profiles().profiles()[0].model_copy(update={"supported": False})
    profiles = ForceFieldCompatibilityRegistry((disabled,))
    issues = _check(_parameterization(), profiles)
    assert [(issue.code, issue.severity) for issue in issues] == [
        ("FF.FAMILY_CONSISTENCY", Severity.DECISION_REQUIRED)
    ]


def test_conflicting_top_level_parameterization_label_blocks():
    parameterization = _parameterization().model_copy(update={"ligand_method": "GAFF2"})
    issues = _check(parameterization)
    assert [(issue.code, issue.severity) for issue in issues] == [
        ("FF.FAMILY_CONSISTENCY", Severity.BLOCKER)
    ]
    assert "ligand_method_component" in issues[0].evidence["mismatches"]


def test_system_must_link_the_checked_parameterization():
    parameterization = _parameterization()
    system = _system(parameterization).model_copy(update={"parameterization_id": new_ulid()})
    issues = default_registry().run(
        "system_build", {"parameterization": parameterization, "md_system": system}
    )
    assert [(issue.code, issue.severity) for issue in issues] == [
        ("FF.FAMILY_CONSISTENCY", Severity.BLOCKER)
    ]
    assert "parameterization_lineage" in issues[0].evidence["mismatches"]
