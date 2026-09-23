"""SQLite-backed cache for normalized task outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

import caddsuite.contracts  # noqa: F401  (register all normalized result contracts)
from caddsuite.contracts.base import VersionedContract, load_contract
from caddsuite.storage.models import TaskCacheRow

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CacheKeyError(ValueError):
    """A malformed digest must never be used as a cache identity."""


@dataclass(frozen=True, slots=True)
class CachedResult:
    cache_key: str
    result: VersionedContract
    source_task_id: str
    created_at: datetime


class ResultCache:
    """First successful result wins for a cache key; concurrent writers cannot overwrite it."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(self, cache_key: str) -> CachedResult | None:
        _validate_key(cache_key)
        with self._sessions() as session:
            row = session.get(TaskCacheRow, cache_key)
            return None if row is None else _cached_result(row)

    def put(
        self, cache_key: str, result: VersionedContract, *, source_task_id: str
    ) -> CachedResult:
        _validate_key(cache_key)
        payload = result.model_dump(mode="json")
        with self._sessions.begin() as session:
            session.execute(
                sqlite_insert(TaskCacheRow)
                .values(
                    cache_key=cache_key,
                    schema_version=result.schema_version,
                    payload=payload,
                    source_task_id=source_task_id,
                )
                .on_conflict_do_nothing(index_elements=[TaskCacheRow.cache_key])
            )
            row = session.scalar(select(TaskCacheRow).where(TaskCacheRow.cache_key == cache_key))
            if row is None:
                raise RuntimeError(f"cache entry {cache_key} was not stored")
            return _cached_result(row)


def _validate_key(cache_key: str) -> None:
    if not _SHA256.fullmatch(cache_key):
        raise CacheKeyError("cache key must be a lowercase SHA-256 digest")


def _cached_result(row: TaskCacheRow) -> CachedResult:
    if row.schema_version != row.payload.get("schema_version"):
        raise RuntimeError(f"cache entry {row.cache_key} has inconsistent contract metadata")
    return CachedResult(
        cache_key=row.cache_key,
        result=load_contract(row.payload),
        source_task_id=row.source_task_id,
        created_at=row.created_at,
    )
