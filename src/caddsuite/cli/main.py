"""``caddsuite`` command-line entry point (Phase 2 subset)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from caddsuite.cli.commands import register_commands
from caddsuite.contracts.schema_export import diff_schemas, export_schemas
from caddsuite.provenance.host import capture_host_info
from caddsuite.provenance.software import platform_ref, snapshot_conda_prefix
from caddsuite.storage import migrate
from caddsuite.storage.paths import database_path, resolve_data_root
from caddsuite.workflow.schema import diff_workflow_schema, export_workflow_schema

app = typer.Typer(no_args_is_help=True, help="CADD Suite: reproducible drug-discovery workflows.")
schemas_app = typer.Typer(no_args_is_help=True, help="Contract JSON Schemas.")
db_app = typer.Typer(no_args_is_help=True, help="Metadata database.")
app.add_typer(schemas_app, name="schemas")
app.add_typer(db_app, name="db")

DataRootOption = Annotated[
    Path | None,
    typer.Option("--data-root", envvar="CADDSUITE_DATA_ROOT", help="Platform data directory."),
]


@app.command()
def version() -> None:
    """Print the platform version and git state."""
    ref = platform_ref()
    typer.echo(json.dumps(ref.model_dump(), indent=2))


@schemas_app.command("export")
def schemas_export(
    out: Annotated[Path, typer.Option(help="Output directory.")] = Path("docs/schemas"),
) -> None:
    """Write a JSON Schema for every registered contract."""
    written = export_schemas(out)
    written.append(export_workflow_schema(out))
    typer.echo(f"wrote {len(written)} files to {out}")


@schemas_app.command("check")
def schemas_check(
    out: Annotated[Path, typer.Option(help="Directory holding committed schemas.")] = Path(
        "docs/schemas"
    ),
) -> None:
    """Fail if committed schemas differ from the current contracts."""
    problems = diff_schemas(out) + diff_workflow_schema(out)
    if problems:
        typer.echo("out of date: " + ", ".join(problems), err=True)
        raise typer.Exit(code=1)
    typer.echo("schemas up to date")


@db_app.command("upgrade")
def db_upgrade(data_root: DataRootOption = None) -> None:
    """Create or migrate the metadata database to the latest schema."""
    path = database_path(resolve_data_root(data_root))
    migrate.upgrade(path)
    typer.echo(f"database at {path} is at revision {migrate.current_revision(path)}")


@app.command("host-info")
def host_info() -> None:
    """Show the host facts that are recorded with every task attempt."""
    typer.echo(capture_host_info().model_dump_json(indent=2))


@app.command("env-snapshot")
def env_snapshot(prefix: Annotated[Path, typer.Argument(help="Conda environment prefix.")]) -> None:
    """Hash a conda environment's exact package set (ADR-0012)."""
    snap = snapshot_conda_prefix(prefix)
    typer.echo(
        json.dumps(
            {
                "prefix": str(snap.prefix),
                "name": snap.name,
                "lock_sha256": snap.lock_sha256,
                "n_packages": len(snap.packages),
                "key_packages": dict(snap.key_packages),
            },
            indent=2,
        )
    )


register_commands(app)


def main() -> None:  # pragma: no cover - thin wrapper
    app()


__all__ = ["app", "main"]
