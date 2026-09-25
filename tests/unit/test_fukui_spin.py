from __future__ import annotations

import pytest

from caddsuite.analysis.fukui import resolve_fukui_spin_states


def test_closed_shell_neutral_uses_frontier_doublets_for_added_and_removed_electron():
    states = resolve_fukui_spin_states(neutral_electrons=10, neutral_multiplicity=1)
    assert states.anion_multiplicity == 2
    assert states.cation_multiplicity == 2
    assert states.selection_policy == "closed_shell_frontier_doublet"


def test_open_shell_neutral_requires_explicit_multiplicity_for_each_charged_state():
    with pytest.raises(ValueError, match="open-shell"):
        resolve_fukui_spin_states(neutral_electrons=7, neutral_multiplicity=2)
    states = resolve_fukui_spin_states(
        neutral_electrons=7,
        neutral_multiplicity=2,
        anion_multiplicity=1,
        cation_multiplicity=1,
    )
    assert states.selection_policy == "explicit_user_multiplicities"
    assert (states.anion_multiplicity, states.cation_multiplicity) == (1, 1)


@pytest.mark.parametrize(
    ("electron_count", "multiplicity", "anion", "cation"),
    [
        (10, 1, 1, 2),
        (7, 2, 2, 1),
        (8, 2, 2, 1),
    ],
)
def test_fukui_spin_states_reject_parity_inconsistent_multiplicity(
    electron_count, multiplicity, anion, cation
):
    with pytest.raises(ValueError, match="parity"):
        resolve_fukui_spin_states(
            neutral_electrons=electron_count,
            neutral_multiplicity=multiplicity,
            anion_multiplicity=anion,
            cation_multiplicity=cation,
        )
