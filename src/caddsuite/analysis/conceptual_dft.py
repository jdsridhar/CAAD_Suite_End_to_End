"""Engine-independent conceptual-DFT descriptors from frontier orbital energies."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import field_validator

from caddsuite.contracts.base import ContractModel, NonEmptyStr


class ConceptualDFTDescriptors(ContractModel):
    """Koopmans estimates; softness is eV inverse and remaining values are eV."""

    method: Literal["koopmans_frontier_orbitals"] = "koopmans_frontier_orbitals"
    homo_eV: float
    lumo_eV: float
    ionization_potential_eV: float
    electron_affinity_eV: float
    chemical_hardness_eV: float
    chemical_potential_eV: float
    chemical_softness_per_eV: float | None
    electrophilicity_eV: float | None
    undefined_reason: NonEmptyStr | None = None
    limitations: tuple[str, ...] = (
        "IP and EA are estimated from frontier orbital energies.",
        "Predictions are not experimental measurements.",
    )

    @field_validator(
        "homo_eV",
        "lumo_eV",
        "ionization_potential_eV",
        "electron_affinity_eV",
        "chemical_hardness_eV",
        "chemical_potential_eV",
        "chemical_softness_per_eV",
        "electrophilicity_eV",
    )
    @classmethod
    def _finite_values(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("descriptor values must be finite")
        return value


def calculate_conceptual_dft(homo_eV: float, lumo_eV: float) -> ConceptualDFTDescriptors:
    """Calculate the legacy descriptor set with explicit validity semantics."""
    if not math.isfinite(homo_eV) or not math.isfinite(lumo_eV):
        raise ValueError("HOMO and LUMO energies must be finite")
    ip, ea = -homo_eV, -lumo_eV
    hardness = (ip - ea) / 2.0
    potential = -(ip + ea) / 2.0
    if hardness <= 0.0:
        softness = electrophilicity = None
        reason = "softness and electrophilicity are undefined for non-positive hardness"
    else:
        softness = 1.0 / (2.0 * hardness)
        electrophilicity = potential**2 / (2.0 * hardness)
        reason = None
    return ConceptualDFTDescriptors(
        homo_eV=homo_eV,
        lumo_eV=lumo_eV,
        ionization_potential_eV=ip,
        electron_affinity_eV=ea,
        chemical_hardness_eV=hardness,
        chemical_potential_eV=potential,
        chemical_softness_per_eV=softness,
        electrophilicity_eV=electrophilicity,
        undefined_reason=reason,
    )
