Alembic revision files. Generate a new one after changing `caddsuite/storage/models.py`:

```bash
python -c "from pathlib import Path; import tempfile; from alembic import command; from caddsuite.storage.migrate import alembic_config, upgrade; d=Path(tempfile.mkdtemp())/'gen.db'; upgrade(d); command.revision(alembic_config(d), message='describe change', autogenerate=True)"
```

Review every generated file by hand. `tests/unit/test_storage.py::test_models_match_migrations`
fails if the models drift from the migration history.
