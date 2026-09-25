"""Engine-side worker runtime (ADR-0002).

This package runs inside foreign conda environments (for example, dft-gui with
Psi4 on Python 3.10). It uses only the Python standard library plus the engine
being wrapped, never the platform core, Pydantic or SQLAlchemy.

The shared protocol is task.json in, then result.json and events.jsonl out.
"""

PROTOCOL_VERSION = "caddsuite.worker/1"
