from caddsuite.adapters.docking.vina_handler import VinaDockingHandler
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind, Conformer
from caddsuite.domain.identity import new_ulid


def test_vina_form_scope_joins_parent_and_conformer_by_stable_lineage() -> None:
    compound = make_compound(
        standardize_smiles("CCO"),
        compound_id=new_ulid(),
        project_id=new_ulid(),
        accession="CMP0001",
        name="ethanol",
        original_text="CCO",
        source="manual",
    )
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound.id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    conformer = Conformer(
        id=new_ulid(),
        form_id=form.id,
        compound_id=compound.id,
        generator="RDKit",
        seed=42,
        structure=ArtifactRef(
            artifact_id=new_ulid(),
            role="ligand_conformer",
            sha256="a" * 64,
        ),
    )
    unrelated_form = CompoundForm(
        id=new_ulid(),
        compound_id=compound.id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles="CCO",
        formal_charge=0,
    )
    handler = object.__new__(VinaDockingHandler)

    assert handler.subject_key("compound_form", form) == str(form.id)
    assert handler.matches_subject("compound_form", form, compound)
    assert handler.matches_subject("compound_form", form, conformer)
    assert handler.matches_subject("compound_form", form, form)
    assert not handler.matches_subject("compound_form", form, unrelated_form)
