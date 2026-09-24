"""Force-field component/profile consistency validation (ADR-0010)."""

from __future__ import annotations

import re
from collections.abc import Iterator

from pydantic import JsonValue

from caddsuite.contracts.md import ForceFieldComponent, MDSystem, Parameterization
from caddsuite.validation.force_field_profiles import (
    ForceFieldCompatibilityRegistry,
    default_force_field_profiles,
)
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue
from caddsuite.validation.registry import RuleContext, RuleRegistry


def _canonical(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def family_consistency(context: RuleContext) -> Iterator[ValidationIssue]:
    """Require a known, exact component profile; unknown combinations need explicit review."""
    parameterization = context.get("parameterization")
    system = context.get("md_system")
    subject = SubjectRef(
        kind="md_system",
        id=system.id if isinstance(system, MDSystem) else None,
        label="force-field compatibility",
    )

    def issue(
        severity: Severity, message: str, evidence: dict[str, JsonValue], remediation: str
    ) -> ValidationIssue:
        return ValidationIssue(
            code="FF.FAMILY_CONSISTENCY",
            severity=severity,
            subject=subject,
            message=message,
            evidence=evidence,
            remediation=(remediation,),
            rule_version="1.0.0",
        )

    if not isinstance(parameterization, Parameterization) or not isinstance(system, MDSystem):
        yield issue(
            Severity.BLOCKER,
            (
                "A typed Parameterization and MDSystem are required for "
                "force-field compatibility validation."
            ),
            {
                "parameterization_present": isinstance(parameterization, Parameterization),
                "md_system_present": isinstance(system, MDSystem),
            },
            "Supply the normalized system-build result; do not bypass compatibility validation.",
        )
        return

    requested_id = parameterization.compatibility_profile_id
    profiles = context.get("force_field_profiles")
    if not isinstance(profiles, ForceFieldCompatibilityRegistry):
        profiles = default_force_field_profiles()
    profile = profiles.get(requested_id) if requested_id else None
    if profile is None:
        yield issue(
            Severity.DECISION_REQUIRED,
            (
                "No registered compatibility profile matches this parameterization; component "
                "labels alone do not establish interoperability."
            ),
            {
                "profile_id": requested_id,
                "family": parameterization.ff_family.value,
                "component_force_fields": {
                    key.value: {"family": value.family.value, "name": value.name}
                    for key, value in parameterization.component_force_fields.items()
                },
                "registered_profiles": [item.profile_id for item in profiles.profiles()],
            },
            (
                "Select a reviewed profile or add and validate a profile for this exact component "
                "combination and output format."
            ),
        )
        return

    declared_components = parameterization.component_force_fields
    expected_components = profile.component_force_fields
    mismatches: dict[str, JsonValue] = {}
    if parameterization.ff_family is not profile.family:
        mismatches["system_family"] = {
            "declared": parameterization.ff_family.value,
            "profile": profile.family.value,
        }
    if system.parameterization_id != parameterization.id:
        mismatches["parameterization_lineage"] = {
            "system_parameterization_id": system.parameterization_id,
            "parameterization_id": parameterization.id,
        }
    top_level_fields = {
        "protein_ff": ForceFieldComponent.PROTEIN,
        "ligand_method": ForceFieldComponent.LIGAND,
        "water_model": ForceFieldComponent.WATER,
        "ion_parameters": ForceFieldComponent.IONS,
    }
    for field_name, component in top_level_fields.items():
        assignment = declared_components.get(component)
        declared_name = getattr(parameterization, field_name)
        if assignment is not None and _canonical(assignment.name) != _canonical(declared_name):
            mismatches[f"{field_name}_component"] = {
                "top_level": declared_name,
                "component_assignment": assignment.name,
            }
    for component in set(declared_components) | set(expected_components):
        actual = declared_components.get(component)
        expected = expected_components.get(component)
        if actual is None or expected is None:
            mismatches[component.value] = {
                "declared": None if actual is None else actual.model_dump(mode="json"),
                "profile": None if expected is None else expected.model_dump(mode="json"),
            }
        elif actual.family is not expected.family or _canonical(actual.name) != _canonical(
            expected.name
        ):
            mismatches[component.value] = {
                "declared": {"family": actual.family.value, "name": actual.name},
                "profile": {"family": expected.family.value, "name": expected.name},
            }
    if _canonical(parameterization.ligand_charge_model) != _canonical(profile.ligand_charge_model):
        mismatches["ligand_charge_model"] = {
            "declared": parameterization.ligand_charge_model,
            "profile": profile.ligand_charge_model,
        }
    topology_format = parameterization.quality.get("topology_format")
    if not isinstance(topology_format, str) or _canonical(topology_format) != _canonical(
        profile.topology_format
    ):
        mismatches["topology_format"] = {
            "declared": topology_format,
            "profile": profile.topology_format,
        }
    if not any(
        _canonical(fmt) == _canonical(profile.topology_format) for fmt in system.engine_inputs
    ):
        mismatches["system_engine_inputs"] = {
            "declared": ", ".join(sorted(system.engine_inputs)),
            "profile_requires": profile.topology_format,
        }
    if mismatches:
        yield issue(
            Severity.BLOCKER,
            (
                "The parameterization declarations or normalized topology format contradict "
                "the selected compatibility profile."
            ),
            {"profile_id": profile.profile_id, "mismatches": mismatches},
            (
                "Correct the source declarations or choose a profile that matches the actual "
                "parameterized system; do not change labels to suppress this issue."
            ),
        )
        return
    if not profile.supported:
        yield issue(
            Severity.DECISION_REQUIRED,
            "The profile is registered for review but is not enabled for execution.",
            {"profile_id": profile.profile_id, "scope_note": profile.scope_note},
            "Complete scientific and engine-format validation before enabling this profile.",
        )


def register(registry: RuleRegistry) -> None:
    registry.rule(
        code="FF.FAMILY_CONSISTENCY",
        version="1.0.0",
        scopes={"system_build"},
        description=(
            "Each parameterization must match an explicitly registered component-family, "
            "charge-model and topology-format profile."
        ),
    )(family_consistency)
