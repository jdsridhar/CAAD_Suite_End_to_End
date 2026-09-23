"""Engine-side worker runtime (ADR-0002).

This package runs **inside foreign conda environments** (e.g. ``dft-gui`` with Psi4 on
Python 3.10). It therefore depends only on the Python standard library plus the engine it
wraps, never on the platform core, Pydantic or SQLAlchemy. That rule is enforced by an
import-linter contract.

Protocol (implemented in Phase 10): ``task.json`` in → ``result.json`` + ``events.jsonl`` out.
"""

PROTOCOL_VERSION = "caddsuite.worker/1"
