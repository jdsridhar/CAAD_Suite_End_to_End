"""Declarative, reviewable parameterization profiles used by FF consistency rules."""

from __future__ import annotations

from caddsuite.contracts.base import ContractModel, NonEmptyStr
from caddsuite.contracts.md import (
    ComponentForceField,
    ForceFieldComponent,
    ForceFieldFamily,
)

CHARMM_GUI_GROMACS_PROFILE_ID = "caddsuite.charmm_gui.gromacs.charmm36m_cgenff_v1"
AMBER_TLEAP_GROMACS_PROFILE_ID = "caddsuite.ambertools.gromacs.ff14sb_gaff2_tip3p_v1"
AMBER_TLEAP_NATIVE_PROFILE_ID = "caddsuite.ambertools.amber.ff14sb_gaff2_tip3p_v1"


class ForceFieldCompatibilityProfile(ContractModel):
    """One reviewed component combination and the topology format it can produce."""

    profile_id: NonEmptyStr
    family: ForceFieldFamily
    component_force_fields: dict[ForceFieldComponent, ComponentForceField]
    ligand_charge_model: NonEmptyStr
    topology_format: NonEmptyStr
    supported: bool = True
    scope_note: NonEmptyStr


class ForceFieldCompatibilityRegistry:
    """Mutable during application/plugin composition; immutable use is the caller's choice."""

    def __init__(self, profiles: tuple[ForceFieldCompatibilityProfile, ...] = ()) -> None:
        self._profiles: dict[str, ForceFieldCompatibilityProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ForceFieldCompatibilityProfile) -> None:
        if profile.profile_id in self._profiles:
            raise ValueError(f"force-field profile {profile.profile_id!r} is already registered")
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> ForceFieldCompatibilityProfile | None:
        return self._profiles.get(profile_id)

    def profiles(self) -> tuple[ForceFieldCompatibilityProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))


def default_force_field_profiles() -> ForceFieldCompatibilityRegistry:
    """Return built-in profiles supported by current adapters, not hypothetical mixes."""
    charmm = ForceFieldFamily.CHARMM
    return ForceFieldCompatibilityRegistry(
        (
            ForceFieldCompatibilityProfile(
                profile_id=CHARMM_GUI_GROMACS_PROFILE_ID,
                family=charmm,
                component_force_fields={
                    ForceFieldComponent.PROTEIN: ComponentForceField(
                        family=charmm, name="CHARMM36m"
                    ),
                    ForceFieldComponent.LIGAND: ComponentForceField(family=charmm, name="CGenFF"),
                    ForceFieldComponent.WATER: ComponentForceField(
                        family=charmm, name="CHARMM TIP3P"
                    ),
                    ForceFieldComponent.IONS: ComponentForceField(
                        family=charmm, name="CHARMM ions"
                    ),
                },
                ligand_charge_model="CGenFF",
                topology_format="GROMACS",
                supported=True,
                scope_note=(
                    "Audited CHARMM-GUI GROMACS import declaration profile; it verifies declared "
                    "component identities and file-format consistency, not force-field accuracy, "
                    "penalty acceptability, or simulation stability."
                ),
            ),
            ForceFieldCompatibilityProfile(
                profile_id=AMBER_TLEAP_GROMACS_PROFILE_ID,
                family=ForceFieldFamily.AMBER,
                component_force_fields={
                    ForceFieldComponent.PROTEIN: ComponentForceField(
                        family=ForceFieldFamily.AMBER, name="ff14SB"
                    ),
                    ForceFieldComponent.LIGAND: ComponentForceField(
                        family=ForceFieldFamily.AMBER, name="GAFF2"
                    ),
                    ForceFieldComponent.WATER: ComponentForceField(
                        family=ForceFieldFamily.AMBER, name="TIP3P"
                    ),
                    ForceFieldComponent.IONS: ComponentForceField(
                        family=ForceFieldFamily.AMBER, name="Joung-Cheatham TIP3P"
                    ),
                },
                ligand_charge_model="AM1-BCC",
                topology_format="GROMACS",
                supported=False,
                scope_note=(
                    "Disabled candidate. One tiny AmberTools-to-GROMACS conversion and "
                    "single-point regression is recorded; multi-system validation and a "
                    "justified energy tolerance are still required."
                ),
            ),
            ForceFieldCompatibilityProfile(
                profile_id=AMBER_TLEAP_NATIVE_PROFILE_ID,
                family=ForceFieldFamily.AMBER,
                component_force_fields={
                    ForceFieldComponent.PROTEIN: ComponentForceField(
                        family=ForceFieldFamily.AMBER, name="ff14SB"
                    ),
                    ForceFieldComponent.LIGAND: ComponentForceField(
                        family=ForceFieldFamily.AMBER, name="GAFF2"
                    ),
                    ForceFieldComponent.WATER: ComponentForceField(
                        family=ForceFieldFamily.AMBER, name="TIP3P"
                    ),
                    ForceFieldComponent.IONS: ComponentForceField(
                        family=ForceFieldFamily.AMBER, name="Joung-Cheatham TIP3P"
                    ),
                },
                ligand_charge_model="AM1-BCC",
                topology_format="AMBER",
                supported=True,
                scope_note=(
                    "Native Amber prmtop/inpcrd execution is enabled for the OpenMM adapter's "
                    "explicit ff14SB/GAFF2/AM1-BCC/TIP3P profile. Current evidence is one tiny "
                    "solvated ethanol + two-residue GLY CPU smoke run; this is format and "
                    "execution compatibility evidence, not broad force-field or scientific "
                    "validation."
                ),
            ),
        )
    )
