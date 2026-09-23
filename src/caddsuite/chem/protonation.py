"""Explicit pH-dependent ligand microstate enumeration and decision handling."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol, cast

from pydantic import Field

from caddsuite.chem.standardize import ChemistryDependencyError, _rdkit
from caddsuite.contracts.base import ContractModel, PHValue, SoftwareRef
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import ULIDStr, new_ulid
from caddsuite.validation.decisions import DecisionOption, DecisionRequest
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class ProtonationPolicy(ContractModel):
    """Versioned inputs to pH-conditioned microstate enumeration."""

    ph: PHValue = 7.4
    precision: float = Field(default=1.0, ge=0)
    max_variants: int = Field(default=128, ge=1, le=4096)


class ProtonationEnumerator(Protocol):
    """Engine interface: return candidate isomeric SMILES for an input and pH policy."""

    name: str
    version: str

    def enumerate(self, smiles: str, policy: ProtonationPolicy) -> Sequence[str]: ...


class ProtonationInputError(ValueError):
    """The supplied parent structure is invalid or cannot be enumerated."""


class ProtonationLimitError(RuntimeError):
    """The enumerator may have truncated candidates at its configured output limit."""


class DimorphiteDLProtonator:
    """Dimorphite-DL implementation of the engine-independent protonation interface."""

    name = "Dimorphite-DL"

    def __init__(self) -> None:
        try:
            self.version = version("dimorphite-dl")
            from dimorphite_dl import protonate_smiles  # type: ignore[import-untyped]
        except (PackageNotFoundError, ImportError) as exc:
            raise ChemistryDependencyError(
                "Dimorphite-DL is required for pH-dependent protonation; "
                "install caddsuite[protonation]"
            ) from exc
        self._protonate_smiles = protonate_smiles

    def enumerate(self, smiles: str, policy: ProtonationPolicy) -> Sequence[str]:
        return cast(
            Sequence[str],
            self._protonate_smiles(
                smiles,
                ph_min=policy.ph,
                ph_max=policy.ph,
                precision=policy.precision,
                max_variants=policy.max_variants,
                label_states=False,
                validate_output=True,
            ),
        )


def _same_heavy_atom_graph(Chem: Any, left: Any, right: Any) -> bool:
    """Require element-preserving graph isomorphism while allowing bond-order shifts."""

    def generic_bond_query(molecule: Any) -> Any:
        editable = Chem.RWMol()
        heavy_indices = [atom.GetIdx() for atom in molecule.GetAtoms() if atom.GetAtomicNum() != 1]
        remap = {old: new for new, old in enumerate(heavy_indices)}
        for old_index in heavy_indices:
            atomic_number = molecule.GetAtomWithIdx(old_index).GetAtomicNum()
            editable.AddAtom(Chem.AtomFromSmarts(f"[#{atomic_number}]"))
        for bond in molecule.GetBonds():
            begin, end = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            if begin in remap and end in remap:
                editable.AddBond(remap[begin], remap[end], Chem.BondType.UNSPECIFIED)
        return editable.GetMol()

    try:
        left_query = generic_bond_query(left)
        right_query = generic_bond_query(right)
        return bool(right.HasSubstructMatch(left_query) and left.HasSubstructMatch(right_query))
    except (AttributeError, RuntimeError, TypeError):
        return False


@dataclass(frozen=True, slots=True)
class ProtonationEnumeration:
    """Enumerated candidate forms; multiple candidates require resolve() before use."""

    forms: tuple[CompoundForm, ...]
    issue: ValidationIssue | None
    decision_request: DecisionRequest | None
    policy: ProtonationPolicy


def enumerate_microstates(
    *,
    compound_id: ULIDStr,
    parent_smiles: str,
    policy: ProtonationPolicy | None = None,
    engine: ProtonationEnumerator | None = None,
) -> ProtonationEnumeration:
    """Enumerate pH-specific forms; pause for a human choice if results are ambiguous."""
    policy = policy or ProtonationPolicy()
    engine = engine or DimorphiteDLProtonator()
    Chem, _rdBase, _descriptors, _standardize, _all_chem = _rdkit()
    parent = Chem.MolFromSmiles(parent_smiles)
    if parent is None:
        raise ProtonationInputError("RDKit could not parse the standardized parent SMILES")

    try:
        candidates = tuple(engine.enumerate(parent_smiles, policy))
    except Exception as exc:
        raise ProtonationInputError(
            f"{engine.name} protonation failed for pH {policy.ph}: {exc}"
        ) from exc
    if len(candidates) >= policy.max_variants:
        raise ProtonationLimitError(
            f"{engine.name} returned {len(candidates)} variants at max_variants="
            f"{policy.max_variants}; possible truncation. Increase the limit before proceeding."
        )

    unique_smiles: dict[str, tuple[str, int]] = {}
    for candidate in candidates:
        molecule = Chem.MolFromSmiles(candidate)
        if molecule is None:
            raise ProtonationInputError(
                f"{engine.name} returned an invalid candidate SMILES: {candidate!r}"
            )
        if not _same_heavy_atom_graph(Chem, parent, molecule):
            raise ProtonationInputError(
                f"{engine.name} changed the element-preserving heavy-atom connectivity"
            )
        canonical = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
        unique_smiles.setdefault(canonical, (canonical, Chem.GetFormalCharge(molecule)))
    ordered = sorted(unique_smiles.values())
    if not ordered:
        raise ProtonationInputError(f"{engine.name} returned no microstates at pH {policy.ph}")

    software = SoftwareRef(
        name=engine.name,
        version=engine.version,
        kind=SoftwareKind.LIBRARY,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )
    forms = tuple(
        CompoundForm(
            id=new_ulid(),
            compound_id=compound_id,
            kind=CompoundFormKind.PROTONATED_MICROSTATE,
            smiles=smiles,
            formal_charge=charge,
            ph=policy.ph,
            method=software,
        )
        for smiles, charge in ordered
    )
    if len(forms) == 1:
        return ProtonationEnumeration(forms, None, None, policy)

    keys = tuple(
        "form_" + hashlib.sha256(form.smiles.encode("utf-8")).hexdigest()[:12] for form in forms
    )
    options = (
        *(
            DecisionOption(
                key=key,
                label=f"Candidate {index}: charge {form.formal_charge:+d}",
                consequence=f"Use microstate SMILES {form.smiles} for downstream calculations.",
            )
            for index, (key, form) in enumerate(zip(keys, forms, strict=True), start=1)
        ),
        DecisionOption(
            key="run_all",
            label="Run all candidate microstates",
            consequence="Create separate downstream calculations for each enumerated form.",
        ),
    )
    request = DecisionRequest(
        issue_code="CHEM.PROTONATION_AMBIGUOUS",
        question=(
            f"{engine.name} enumerated {len(forms)} distinct forms at pH {policy.ph}. "
            "Choose one microstate or run all as separate forms."
        ),
        options=options,
    )
    issue = ValidationIssue(
        code="CHEM.PROTONATION_AMBIGUOUS",
        severity=Severity.DECISION_REQUIRED,
        subject=SubjectRef(kind="compound", id=compound_id),
        message=request.question,
        evidence={
            "pH": policy.ph,
            "engine": engine.name,
            "engine_version": engine.version,
            "candidate_count": len(forms),
            "candidate_smiles": [form.smiles for form in forms],
        },
        remediation=(
            "Select one candidate form based on the intended experimental conditions",
            "Run all candidates as separate forms and compare downstream results",
        ),
        rule_version="1.0",
    )
    return ProtonationEnumeration(forms, issue, request, policy)


def resolve_microstates(
    enumeration: ProtonationEnumeration, chosen_key: str
) -> tuple[CompoundForm, ...]:
    """Resolve a single form or the explicit run_all decision; reject stale/unknown choices."""
    if enumeration.decision_request is None:
        if chosen_key in {"single", "run_all"}:
            return enumeration.forms
        raise ValueError("a single unambiguous form only accepts 'single' or 'run_all'")
    if chosen_key == "run_all":
        return enumeration.forms
    selected = next(
        (
            form
            for form in enumeration.forms
            if "form_" + hashlib.sha256(form.smiles.encode("utf-8")).hexdigest()[:12] == chosen_key
        ),
        None,
    )
    if selected is None:
        raise ValueError(f"unknown protonation decision option {chosen_key!r}")
    return (selected,)
