"""Schema migrations (Alembic), driven programmatically; no alembic.ini needed.

Why migrations from day one: the database will hold years of provenance. Schema changes
must be explicit, reviewable and reversible, never "delete the DB and start over".
A test (``tests/unit/test_storage.py``) asserts that the ORM models and the migration
history never drift apart (``alembic check``).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from caddsuite.storage.db import create_db_engine, sqlite_url

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(db_path))
    cfg.attributes["db_path"] = str(db_path)
    return cfg


def upgrade(db_path: Path, revision: str = "head") -> None:
    """Create or upgrade the database at ``db_path`` to ``revision``."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(db_path), revision)


def check(db_path: Path) -> None:
    """Raise if the ORM models contain changes not captured by a migration."""
    command.check(alembic_config(db_path))


def current_revision(db_path: Path) -> str | None:
    engine = create_db_engine(db_path)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
