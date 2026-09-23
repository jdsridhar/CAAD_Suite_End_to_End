"""Conservative mmCIF analysis for polymer-chain and ligand selection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from caddsuite.contracts.structure import (
    LigandCandidate,
    PolymerChainCandidate,
    Structure,
    StructureSplit,
)
from caddsuite.domain.identity import new_ulid
from caddsuite.structure.mmcif import parse_mmcif
from caddsuite.validation.decisions import DecisionOption, DecisionRequest
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue

_WATERS = {"HOH", "WAT", "DOD"}
_IONS = {"NA", "K", "CL", "CA", "MG", "ZN", "FE", "MN", "CU", "CO", "NI"}
_METALS = {"ZN", "FE", "MN", "CU", "CO", "NI"}
_COFACTORS = {"HEM", "HEC", "FAD", "FMN", "NAD", "NAP", "ATP", "ADP", "COA", "PLP"}
_ADDITIVES = {"GOL", "EDO", "PEG", "PGE", "DMS", "SO4", "PO4", "ACT", "FMT"}


@dataclass(frozen=True, slots=True)
class StructureSplitAnalysis:
    split: StructureSplit
    issues: tuple[ValidationIssue, ...]
    decision_requests: tuple[DecisionRequest, ...]


def _column(cif: dict[str, Any], key: str, count: int | None = None) -> list[str]:
    value = cif.get(key, [])
    values = [value] if isinstance(value, str) else [str(item) for item in value]
    if count is not None and len(values) == 1 and count > 1:
        values *= count
    return values


def _clean(value: str | None) -> str | None:
    return value if value not in {None, ".", "?"} else None


def _candidate_key(kind: str, *values: str) -> str:
    digest = hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()[:14]
    return f"{kind}_{digest}"


def _component_category(
    resname: str, elements: set[str], atom_count: int
) -> Literal["water", "ligand", "cofactor", "additive", "ion", "metal", "other"]:
    upper = resname.upper()
    if upper in _WATERS:
        return "water"
    if upper in _COFACTORS:
        return "cofactor"
    if upper in _ADDITIVES:
        return "additive"
    if upper in _IONS or atom_count == 1:
        return "metal" if upper in _METALS or elements & _METALS else "ion"
    return "ligand"


def analyze_structure_split(structure: Structure, cif_bytes: bytes) -> StructureSplitAnalysis:
    """Retain entity_poly sequences and enumerate candidate chains/components.

    The original mmCIF artifact remains untouched and authoritative. This operation only
    creates a normalized selection inventory; it does not discard unresolved chains or
    non-polymer components.
    """
    cif = parse_mmcif(cif_bytes)
    entity_ids = _column(cif, "_entity_poly.entity_id")
    raw_sequences = _column(cif, "_entity_poly.pdbx_seq_one_letter_code_can")
    if len(entity_ids) != len(raw_sequences):
        raise ValueError("entity_poly sequence columns have inconsistent lengths")
    sequences = {
        entity_id: "".join(sequence.split()).replace("?", "")
        for entity_id, sequence in zip(entity_ids, raw_sequences, strict=True)
    }
    entity_names = _column(cif, "_entity.id")
    entity_descriptions = _column(cif, "_entity.pdbx_description")
    if len(entity_names) != len(entity_descriptions):
        raise ValueError("entity description columns have inconsistent lengths")
    descriptions = dict(zip(entity_names, entity_descriptions, strict=True))
    raw_polymer_types = _column(cif, "_entity_poly.type")
    if len(entity_ids) != len(raw_polymer_types):
        raise ValueError("entity_poly type columns have inconsistent lengths")
    polymer_types = dict(zip(entity_ids, raw_polymer_types, strict=True))
    asym_ids = _column(cif, "_struct_asym.id")
    asym_entities = _column(cif, "_struct_asym.entity_id")
    if len(asym_ids) != len(asym_entities):
        raise ValueError("struct_asym columns have inconsistent lengths")
    asym_to_entity = dict(zip(asym_ids, asym_entities, strict=True))

    atom_fields = {
        key: _column(cif, key)
        for key in (
            "_atom_site.group_PDB",
            "_atom_site.label_atom_id",
            "_atom_site.label_comp_id",
            "_atom_site.label_asym_id",
            "_atom_site.label_entity_id",
            "_atom_site.label_seq_id",
            "_atom_site.auth_asym_id",
            "_atom_site.auth_seq_id",
            "_atom_site.pdbx_PDB_ins_code",
            "_atom_site.type_symbol",
            "_atom_site.pdbx_PDB_model_num",
        )
    }
    lengths = {len(values) for values in atom_fields.values()}
    if len(lengths) != 1:
        raise ValueError("atom_site columns have inconsistent lengths")
    atom_count = lengths.pop() if lengths else 0

    auth_chain: dict[str, str] = {}
    observed_residues: dict[str, set[str]] = {}
    components: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for index in range(atom_count):

        def get(field: str, atom_index: int = index) -> str:
            return atom_fields[f"_atom_site.{field}"][atom_index]

        model_num = _clean(get("pdbx_PDB_model_num"))
        if model_num not in {None, "1"}:
            continue
        group = get("group_PDB")
        label_chain = get("label_asym_id")
        entity_id = _clean(get("label_entity_id"))
        auth_id = _clean(get("auth_asym_id"))
        auth_chain.setdefault(label_chain, auth_id or label_chain)
        if group == "ATOM" and entity_id is not None:
            if entity_id in sequences:
                observed_residues.setdefault(label_chain, set()).add(
                    f"{get('label_seq_id')}:{get('label_comp_id')}"
                )
            continue
        if group != "HETATM":
            continue
        resname = get("label_comp_id")
        if resname.upper() in _WATERS:
            continue
        auth_seq = _clean(get("auth_seq_id")) or _clean(get("label_seq_id")) or ""
        insertion_code = _clean(get("pdbx_PDB_ins_code")) or ""
        key = (
            resname,
            label_chain,
            auth_id or label_chain,
            entity_id or "",
            auth_seq,
            insertion_code,
        )
        component = components.setdefault(
            key,
            {"elements": set(), "atoms": set()},
        )
        component["elements"].add(get("type_symbol").upper())
        component["atoms"].add(get("label_atom_id"))

    chains: list[PolymerChainCandidate] = []
    for label_chain, entity_id in asym_to_entity.items():
        molecule_type = polymer_types.get(entity_id, "")
        if not molecule_type.lower().startswith("polypeptide"):
            continue
        chains.append(
            PolymerChainCandidate(
                label_asym_id=label_chain,
                auth_asym_id=auth_chain.get(label_chain),
                entity_id=entity_id,
                description=descriptions.get(entity_id),
                sequence=sequences.get(entity_id, ""),
                molecule_type=molecule_type,
                observed_residue_count=len(observed_residues.get(label_chain, set())),
            )
        )
    chains.sort(key=lambda chain: chain.label_asym_id)

    chem_comp_ids = _column(cif, "_chem_comp.id")
    chem_comp_names = _column(cif, "_chem_comp.name")
    if len(chem_comp_ids) != len(chem_comp_names):
        raise ValueError("chem_comp ID and name columns have inconsistent lengths")
    component_names = dict(zip(chem_comp_ids, chem_comp_names, strict=True))
    ligands: list[LigandCandidate] = []
    for (resname, label_chain, auth_id, entity_id, auth_seq, insertion_code), details in sorted(
        components.items()
    ):
        category = _component_category(resname, details["elements"], len(details["atoms"]))
        if category == "water":
            continue
        ligands.append(
            LigandCandidate(
                component_id=resname,
                label_asym_id=label_chain,
                auth_asym_id=auth_id,
                label_entity_id=entity_id or None,
                auth_seq_id=auth_seq or None,
                insertion_code=insertion_code or None,
                name=_clean(component_names.get(resname)),
                category=category,
                atom_count=len(details["atoms"]),
            )
        )

    split = StructureSplit(
        id=new_ulid(),
        structure_id=structure.id,
        polymer_chains=tuple(chains),
        ligand_candidates=tuple(ligands),
        entity_sequences=sequences,
    )
    issues: list[ValidationIssue] = []
    requests: list[DecisionRequest] = []
    protein_chains = tuple(chains)
    if not protein_chains:
        issues.append(
            ValidationIssue(
                code="STRUCTURE.NO_POLYMER_CHAIN",
                severity=Severity.BLOCKER,
                subject=SubjectRef(kind="structure", id=structure.id),
                message="The mmCIF contains no polypeptide chain suitable for a protein target.",
                evidence={"entry_id": structure.source_id},
                remediation=("Select a protein-containing structure or inspect the source entry",),
                rule_version="1.0",
            )
        )
    if len(protein_chains) > 1:
        options = (
            *(
                DecisionOption(
                    key=_candidate_key("chain", chain.label_asym_id, chain.entity_id),
                    label=f"Chain {chain.auth_asym_id or chain.label_asym_id}",
                    consequence=(
                        f"Use polymer entity {chain.entity_id}, chain "
                        f"{chain.auth_asym_id or chain.label_asym_id}."
                    ),
                )
                for chain in protein_chains
            ),
            DecisionOption(
                key="all_chains",
                label="Use all protein chains",
                consequence="Keep every detected polypeptide chain in the receptor.",
            ),
        )
        request = DecisionRequest(
            issue_code="STRUCTURE.CHAIN_AMBIGUOUS",
            question=(
                f"Entry contains {len(protein_chains)} polypeptide chains; "
                "choose receptor chain(s)."
            ),
            options=options,
        )
        requests.append(request)
        issues.append(
            ValidationIssue(
                code="STRUCTURE.CHAIN_AMBIGUOUS",
                severity=Severity.DECISION_REQUIRED,
                subject=SubjectRef(kind="structure", id=structure.id),
                message=request.question,
                evidence={"chain_ids": [chain.label_asym_id for chain in protein_chains]},
                remediation=("Select a chain, or explicitly keep all protein chains",),
                rule_version="1.0",
            )
        )
    ligand_choices = tuple(
        ligand for ligand in ligands if ligand.category in {"ligand", "cofactor"}
    )
    if len(ligand_choices) > 1:
        options = (
            *(
                DecisionOption(
                    key=_candidate_key(
                        "ligand",
                        ligand.component_id,
                        ligand.label_asym_id,
                        ligand.auth_seq_id or "",
                        ligand.insertion_code or "",
                    ),
                    label=(
                        f"{ligand.component_id}, chain "
                        f"{ligand.auth_asym_id or ligand.label_asym_id}, residue "
                        f"{ligand.auth_seq_id or '?'}{ligand.insertion_code or ''} "
                        f"({ligand.category})"
                    ),
                    consequence=(
                        f"Use {ligand.component_id} at "
                        f"{ligand.auth_asym_id or ligand.label_asym_id}:"
                        f"{ligand.auth_seq_id or '?'}{ligand.insertion_code or ''} "
                        "as the reference ligand."
                    ),
                )
                for ligand in ligand_choices
            ),
            DecisionOption(
                key="skip_reference",
                label="Do not use a reference ligand",
                consequence="Continue without inferring a reference-ligand binding site.",
            ),
        )
        request = DecisionRequest(
            issue_code="STRUCTURE.LIGAND_AMBIGUOUS",
            question=(
                f"Entry contains {len(ligand_choices)} ligand/cofactor instances; "
                "choose the intended reference ligand."
            ),
            options=options,
        )
        requests.append(request)
        issues.append(
            ValidationIssue(
                code="STRUCTURE.LIGAND_AMBIGUOUS",
                severity=Severity.DECISION_REQUIRED,
                subject=SubjectRef(kind="structure", id=structure.id),
                message=request.question,
                evidence={
                    "candidates": [
                        {
                            "component_id": ligand.component_id,
                            "chain": ligand.label_asym_id,
                            "auth_seq_id": ligand.auth_seq_id,
                        }
                        for ligand in ligand_choices
                    ]
                },
                remediation=(
                    "Select the cognate ligand or explicitly skip reference-ligand selection",
                ),
                rule_version="1.0",
            )
        )
    return StructureSplitAnalysis(split, tuple(issues), tuple(requests))


class IncompatibleStructureSelection(ValueError):
    """Chosen ligand reference is not associated with the selected polymer chain."""


@dataclass(frozen=True, slots=True)
class ResolvedStructureSelection:
    polymer_chains: tuple[PolymerChainCandidate, ...]
    reference_ligand: LigandCandidate | None


def resolve_structure_selection(
    analysis: StructureSplitAnalysis,
    *,
    chain_key: str | None = None,
    ligand_key: str | None = None,
) -> ResolvedStructureSelection:
    """Resolve explicit decisions; auto-select only when a category has one candidate."""
    chains = analysis.split.polymer_chains
    selected_chains: tuple[PolymerChainCandidate, ...]
    if len(chains) == 1 and chain_key in {None, "single"}:
        selected_chains = chains
    elif len(chains) > 1:
        if chain_key == "all_chains":
            selected_chains = chains
        else:
            selected_chains = tuple(
                chain
                for chain in chains
                if chain_key == _candidate_key("chain", chain.label_asym_id, chain.entity_id)
            )
            if not selected_chains:
                raise ValueError("a valid chain decision is required for this structure")
    else:
        selected_chains = ()

    ligands = tuple(
        ligand
        for ligand in analysis.split.ligand_candidates
        if ligand.category in {"ligand", "cofactor"}
    )
    if len(ligands) == 1 and ligand_key in {None, "single"}:
        reference = ligands[0]
    elif not ligands or ligand_key == "skip_reference":
        reference = None
    else:
        reference = next(
            (
                ligand
                for ligand in ligands
                if ligand_key
                == _candidate_key(
                    "ligand",
                    ligand.component_id,
                    ligand.label_asym_id,
                    ligand.auth_seq_id or "",
                    ligand.insertion_code or "",
                )
            ),
            None,
        )
        if reference is None:
            raise ValueError("a valid ligand decision is required for this structure")
    if (
        reference is not None
        and len(selected_chains) == 1
        and reference.auth_asym_id
        and selected_chains[0].auth_asym_id
        and reference.auth_asym_id != selected_chains[0].auth_asym_id
    ):
        raise IncompatibleStructureSelection(
            f"reference ligand {reference.component_id} belongs to author chain "
            f"{reference.auth_asym_id}, but the selected protein chain is "
            f"{selected_chains[0].auth_asym_id}; choose the matching chain or retain all chains"
        )
    return ResolvedStructureSelection(selected_chains, reference)
