from __future__ import annotations

import math

import pytest

from caddsuite.analysis.conceptual_dft import calculate_conceptual_dft


def test_descriptor_values_and_units_follow_frontier_orbital_formulas() -> None:
    result = calculate_conceptual_dft(-6.0, -2.0)
    assert (result.ionization_potential_eV, result.electron_affinity_eV) == (6.0, 2.0)
    assert (result.chemical_hardness_eV, result.chemical_potential_eV) == (2.0, -4.0)
    assert (result.chemical_softness_per_eV, result.electrophilicity_eV) == (0.25, 4.0)
    assert result.method == "koopmans_frontier_orbitals"


@pytest.mark.parametrize(("homo", "lumo"), [(-4.0, -4.0), (-3.0, -5.0)])
def test_nonpositive_hardness_is_undefined(homo: float, lumo: float) -> None:
    result = calculate_conceptual_dft(homo, lumo)
    assert result.chemical_softness_per_eV is None
    assert result.electrophilicity_eV is None
    assert result.undefined_reason is not None


@pytest.mark.parametrize(("homo", "lumo"), [(math.nan, -1.0), (-1.0, math.inf)])
def test_nonfinite_orbitals_rejected(homo: float, lumo: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        calculate_conceptual_dft(homo, lumo)


def test_result_is_strict_json_payload() -> None:
    result = calculate_conceptual_dft(-6.0, -2.0)
    payload = result.model_dump(mode="json")
    assert payload["chemical_softness_per_eV"] == 0.25
    with pytest.raises(Exception, match="extra"):
        type(result).model_validate({**payload, "extra": 1})
