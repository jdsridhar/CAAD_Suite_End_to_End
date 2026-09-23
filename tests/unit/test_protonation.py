"""pH-conditioned forms record their method and make ambiguity explicit."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from caddsuite.chem.protonation import (
    DimorphiteDLProtonator,
    ProtonationInputError,
    ProtonationLimitError,
    ProtonationPolicy,
    enumerate_microstates,
    resolve_microstates,
)
from caddsuite.domain.identity import new_ulid
from caddsuite.validation.issues import Severity


class FakeEnumerator:
    name = "fake-protonator"
    version = "9.1"

    def __init__(self, candidates: Sequence[str]) -> None:
        self.candidates = candidates

    def enumerate(self, smiles: str, policy: ProtonationPolicy) -> Sequence[str]:
        assert smiles
        assert policy.ph == 7.4
        return self.candidates


def test_known_acid_protonates_to_single_deprotonated_form() -> None:
    engine = DimorphiteDLProtonator()
    result = enumerate_microstates(
        compound_id=new_ulid(),
        parent_smiles="CC(=O)O",
        engine=engine,
    )
    assert len(result.forms) == 1
    form = result.forms[0]
    assert form.smiles == "CC(=O)[O-]"
    assert form.formal_charge == -1
    assert form.ph == 7.4
    assert form.method is not None
    assert form.method.name == "Dimorphite-DL"
    assert form.method.version == "2.0.2"
    assert result.issue is None
    assert result.decision_request is None


def test_multiple_states_pause_and_allow_select_one_or_run_all() -> None:
    result = enumerate_microstates(
        compound_id=new_ulid(),
        parent_smiles="CN(C)C",
        engine=DimorphiteDLProtonator(),
    )
    assert len(result.forms) == 2
    assert result.issue is not None
    assert result.issue.severity is Severity.DECISION_REQUIRED
    assert result.issue.code == "CHEM.PROTONATION_AMBIGUOUS"
    assert result.decision_request is not None
    assert any(option.key == "run_all" for option in result.decision_request.options)
    assert len(resolve_microstates(result, "run_all")) == 2
    selected_key = next(
        option.key for option in result.decision_request.options if option.key != "run_all"
    )
    selected = resolve_microstates(result, selected_key)
    assert len(selected) == 1
    assert selected[0] in result.forms


def test_candidate_enumeration_is_canonicalized_and_deduplicated() -> None:
    result = enumerate_microstates(
        compound_id=new_ulid(),
        parent_smiles="CCO",
        engine=FakeEnumerator(["OCC", "CCO"]),
    )
    assert len(result.forms) == 1
    assert result.forms[0].smiles == "CCO"
    assert result.issue is None


@pytest.mark.parametrize(
    ("smiles", "candidates"),
    [
        ("bad(", ["CCO"]),
        ("CCO", []),
        ("CCO", ["CCCC"]),
        ("CCO", ["COC"]),
    ],
)
def test_invalid_or_empty_engine_outputs_fail_closed(smiles: str, candidates: list[str]) -> None:
    with pytest.raises(ProtonationInputError):
        enumerate_microstates(
            compound_id=new_ulid(),
            parent_smiles=smiles,
            engine=FakeEnumerator(candidates),
        )


def test_possible_engine_truncation_requires_larger_limit() -> None:
    with pytest.raises(ProtonationLimitError, match="possible truncation"):
        enumerate_microstates(
            compound_id=new_ulid(),
            parent_smiles="CN(C)C",
            policy=ProtonationPolicy(max_variants=2),
            engine=FakeEnumerator(["CN(C)C", "C[NH+](C)C"]),
        )


def test_unknown_decision_option_is_rejected() -> None:
    result = enumerate_microstates(
        compound_id=new_ulid(),
        parent_smiles="CN(C)C",
        engine=DimorphiteDLProtonator(),
    )
    with pytest.raises(ValueError, match="unknown protonation"):
        resolve_microstates(result, "form_unknown")
