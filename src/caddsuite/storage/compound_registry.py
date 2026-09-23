"""Transactional project-level compound registry keyed by standardized InChIKey."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.registry import Compound, InputRecord
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.accessions import next_compound_accession
from caddsuite.storage.models import CompoundInputRow, CompoundRow


@dataclass(frozen=True, slots=True)
class RegisteredCompound:
    compound: Compound
    created: bool
    input_record_id: str


class CompoundRegistry:
    """Deduplicate parent identities per project while retaining every raw submission."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def register(
        self,
        *,
        project_id: str,
        inchikey: str,
        input_record: InputRecord,
        create_compound: Callable[[str], Compound],
    ) -> RegisteredCompound:
        """Create or retrieve a compound; the factory receives the allocated accession."""
        try:
            return self._register_transaction(
                project_id=project_id,
                inchikey=inchikey,
                input_record=input_record,
                create_compound=create_compound,
            )
        except IntegrityError:
            # A concurrent transaction may have committed the same InChIKey after our lookup.
            existing = self._existing(project_id, inchikey)
            if existing is None:
                raise
            return self._record_existing(existing, input_record)

    def _register_transaction(
        self,
        *,
        project_id: str,
        inchikey: str,
        input_record: InputRecord,
        create_compound: Callable[[str], Compound],
    ) -> RegisteredCompound:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(CompoundRow).where(
                    CompoundRow.project_id == project_id,
                    CompoundRow.inchikey == inchikey,
                )
            )
            if row is not None:
                compound = Compound.model_validate(row.payload)
                submission = self._add_input(session, row.id, input_record)
                session.flush()
                return RegisteredCompound(compound, False, submission.id)

            accession = next_compound_accession(session, project_id)
            compound = create_compound(accession)
            if (
                compound.project_id != project_id
                or compound.parent.inchikey != inchikey
                or compound.accession != accession
            ):
                raise ValueError(
                    "compound factory must preserve project, InChIKey, and allocated accession"
                )
            row = CompoundRow(
                id=compound.id,
                project_id=compound.project_id,
                accession=compound.accession,
                name=compound.name,
                inchikey=compound.parent.inchikey,
                payload=compound.model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            submission = self._add_input(session, row.id, input_record)
            session.flush()
            return RegisteredCompound(compound, True, submission.id)

    def _existing(self, project_id: str, inchikey: str) -> CompoundRow | None:
        with self._sessions() as session:
            return session.scalar(
                select(CompoundRow).where(
                    CompoundRow.project_id == project_id,
                    CompoundRow.inchikey == inchikey,
                )
            )

    def _record_existing(self, row: CompoundRow, input_record: InputRecord) -> RegisteredCompound:
        compound = Compound.model_validate(row.payload)
        with self._sessions.begin() as session:
            submission = self._add_input(session, row.id, input_record)
            session.flush()
            submission_id = submission.id
        return RegisteredCompound(compound, False, submission_id)

    @staticmethod
    def _add_input(
        session: Session, compound_id: str, input_record: InputRecord
    ) -> CompoundInputRow:
        row = CompoundInputRow(
            id=new_ulid(),
            compound_id=compound_id,
            payload=input_record.model_dump(mode="json"),
        )
        session.add(row)
        return row
