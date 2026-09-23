"""SQLite engine configuration.

Pragmas set on every connection:

* ``foreign_keys=ON``: SQLite ignores foreign keys unless asked; provenance links must
  never dangle.
* ``journal_mode=WAL``: readers (UI, CLI status) don't block the scheduler's writes.
* ``synchronous=NORMAL``: safe with WAL and much faster than FULL.
* ``busy_timeout=5000``: wait up to 5 s for a lock instead of failing immediately.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def create_db_engine(path: Path, *, echo: bool = False) -> Engine:
    """Create an engine for the SQLite database at ``path`` (parent dirs are created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(sqlite_url(path), echo=echo)
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
