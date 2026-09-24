"""Built-in validation rules, grouped by scientific area.

Each rule's docstring cites the audit finding it guards against (docs/ARCHITECTURE_AUDIT.md §8).
"""

from __future__ import annotations

from caddsuite.validation.registry import RuleRegistry
from caddsuite.validation.rules import binding_energy, docking, force_field, md


def register_builtin_rules(registry: RuleRegistry) -> None:
    """Register every built-in rule into ``registry`` (explicit, no import magic)."""
    docking.register(registry)
    md.register(registry)
    force_field.register(registry)
    binding_energy.register(registry)
