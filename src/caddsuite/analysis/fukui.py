"""Spin-state validation for finite-difference Fukui charge-state calculations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FukuiSpinStates:
    """Resolved multiplicities for neutral, N+1 (anion), and N-1 (cation) systems."""

    neutral_multiplicity: int
    anion_multiplicity: int
    cation_multiplicity: int
    selection_policy: str


def _validate_multiplicity(electron_count: int, multiplicity: int, label: str) -> None:
    if multiplicity < 1 or electron_count < multiplicity - 1:
        raise ValueError(f"{label} multiplicity is incompatible with its electron count")
    if (electron_count - multiplicity + 1) % 2:
        raise ValueError(f"{label} electron count and multiplicity have incompatible parity")


def resolve_fukui_spin_states(
    *,
    neutral_electrons: int,
    neutral_multiplicity: int,
    anion_multiplicity: int | None = None,
    cation_multiplicity: int | None = None,
) -> FukuiSpinStates:
    """Validate N/N+1/N-1 spin states without guessing open-shell states.

    A closed-shell singlet uses the frontier-electron doublet for both charged
    legs unless explicitly overridden. For any open-shell neutral, each missing
    charged-state multiplicity is ambiguous and must be supplied by the user.
    This checks electron/multiplicity parity; it does not predict the lowest
    energetic coupling between open-shell fragments.
    """
    if neutral_electrons < 1:
        raise ValueError("neutral_electrons must be positive")
    _validate_multiplicity(neutral_electrons, neutral_multiplicity, "neutral")
    if neutral_multiplicity == 1:
        anion = 2 if anion_multiplicity is None else anion_multiplicity
        cation = 2 if cation_multiplicity is None else cation_multiplicity
        policy = (
            "explicit_user_multiplicities"
            if anion_multiplicity is not None or cation_multiplicity is not None
            else "closed_shell_frontier_doublet"
        )
    else:
        if anion_multiplicity is None or cation_multiplicity is None:
            raise ValueError(
                "open-shell neutral Fukui calculations require explicit "
                "anion and cation multiplicities"
            )
        anion = anion_multiplicity
        cation = cation_multiplicity
        policy = "explicit_user_multiplicities"
    _validate_multiplicity(neutral_electrons + 1, anion, "anion (N+1)")
    _validate_multiplicity(neutral_electrons - 1, cation, "cation (N-1)")
    return FukuiSpinStates(
        neutral_multiplicity=neutral_multiplicity,
        anion_multiplicity=anion,
        cation_multiplicity=cation,
        selection_policy=policy,
    )
