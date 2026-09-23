"""Compound identity deduplication retains every original user submission."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.registry import InputRecord
from caddsuite.domain.identity import new_ulid
from caddsuite.storage import migrate
from caddsuite.storage.compound_registry import CompoundRegistry
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import CompoundInputRow, CompoundRow, ProjectRow


def test_registry_deduplicates_parent_but_preserves_raw_inputs(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.db"
    migrate.upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="registry-test", name="Registry test")
        second_project = ProjectRow(slug="registry-test-2", name="Registry test 2")
        session.add_all([project, second_project])
    registry = CompoundRegistry(sessions)
    sodium = "[Na]OC(=O)CNc1cc(CCC(=O)Nc2ccc(c(c2)C)F)ccc1OC"
    acid = "COc1ccc(CCC(=O)Nc2ccc(F)c(C)c2)cc1NCC(=O)O"
    standardized = standardize_smiles(sodium)
    project_id = project.id

    def create(accession: str, raw: str):
        return make_compound(
            standardized,
            compound_id=new_ulid(),
            project_id=project_id,
            accession=accession,
            name="RC8",
            original_text=raw,
            source="manual",
        )

    first_input = InputRecord(source="manual", original_text=sodium)
    first = registry.register(
        project_id=project_id,
        inchikey=standardized.identity.inchikey,
        input_record=first_input,
        create_compound=lambda accession: create(accession, sodium),
    )
    second_input = InputRecord(source="manual", original_text=acid)
    second = registry.register(
        project_id=project_id,
        inchikey=standardized.identity.inchikey,
        input_record=second_input,
        create_compound=lambda accession: create(accession, acid),
    )

    assert first.created is True
    assert second.created is False
    assert first.compound.id == second.compound.id
    assert first.compound.accession == second.compound.accession == "CMP0001"
    assert first.compound.input_record.original_text == sodium
    with sessions() as session:
        compound_row = session.scalar(
            select(CompoundRow).where(CompoundRow.project_id == project_id)
        )
        assert compound_row is not None
        inputs = list(
            session.scalars(select(CompoundInputRow).order_by(CompoundInputRow.created_at))
        )
        assert len(inputs) == 2
        assert {row.payload["original_text"] for row in inputs} == {sodium, acid}

    other_project_id = second_project.id
    other_standardized = standardize_smiles(sodium)
    separate = registry.register(
        project_id=other_project_id,
        inchikey=other_standardized.identity.inchikey,
        input_record=first_input,
        create_compound=lambda accession: make_compound(
            other_standardized,
            compound_id=new_ulid(),
            project_id=other_project_id,
            accession=accession,
            name="RC8",
            original_text=sodium,
            source="manual",
        ),
    )
    assert separate.created is True
    assert separate.compound.accession == "CMP0001"
    assert separate.compound.id != first.compound.id
    engine.dispose()
