"""CADD Suite: an extensible, reproducible computational drug-discovery platform.

The package is organized in layers (docs/architecture/TARGET_ARCHITECTURE.md §3):

- ``domain`` / ``contracts``: engine-independent scientific data (pure, no I/O)
- ``validation``: scientific compatibility rules (audit findings become rules)
- ``ports`` / ``adapters``: engine interfaces and their implementations
- ``workflow`` / ``execution``: orchestration and process management
- ``storage`` / ``provenance``: database, artifact store, provenance capture
- ``api`` / ``cli``: presentation

Layering is enforced by import-linter contracts (``pyproject.toml``).
"""

__version__ = "0.1.0.dev0"
