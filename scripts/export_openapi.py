"""Export FastAPI OpenAPI contract for client generation."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from tempfile import TemporaryDirectory
from caddsuite.api.provenance import create_app

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/api/openapi.json"))
    args = parser.parse_args()
    with TemporaryDirectory(prefix="caddsuite-openapi-") as data_root:
        app = create_app(data_root=Path(data_root), token="openapi-export")
        schema = app.openapi()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        app.state.sessions.kw["bind"].dispose()

if __name__ == "__main__":
    main()
