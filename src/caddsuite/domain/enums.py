"""Enumerations shared across layers.

String-valued enums (``StrEnum``) serialize to readable JSON and database values, and
comparisons such as ``state == "running"`` still behave.
"""

from __future__ import annotations

from enum import StrEnum


class EngineFamily(StrEnum):
    """Adapter families, one per port (TARGET_ARCHITECTURE §5.2)."""

    STRUCTURE_SOURCE = "structure_source"
    PROTONATION = "protonation"
    DOCKING = "docking"
    SYSTEM_BUILDER = "system_builder"
    MD = "md"
    TRAJECTORY_ANALYSIS = "trajectory_analysis"
    BINDING_ENERGY = "binding_energy"
    QM = "qm"
    PROPERTY_PREDICTION = "property_prediction"
    INTERACTION_PROFILING = "interaction_profiling"
    REPORTING = "reporting"


class LicenseClass(StrEnum):
    """License class of an engine or dependency (ADR-0013)."""

    OPEN_SOURCE_PERMISSIVE = "open_source_permissive"
    OPEN_SOURCE_WEAK_COPYLEFT = "open_source_weak_copyleft"
    OPEN_SOURCE_COPYLEFT = "open_source_copyleft"
    ACADEMIC_NONCOMMERCIAL = "academic_noncommercial"
    COMMERCIAL = "commercial"
    WEB_SERVICE = "web_service"
    UNKNOWN = "unknown"


class SoftwareKind(StrEnum):
    """Role a piece of software plays in a provenance record."""

    ENGINE = "engine"
    ADAPTER = "adapter"
    LIBRARY = "library"
    PLATFORM = "platform"
    SERVICE = "service"
    MANUAL_STEP = "manual_step"  # e.g. a CHARMM-GUI session performed by a person


class TaskState(StrEnum):
    """Workflow task states (TARGET_ARCHITECTURE §8.2)."""

    PENDING = "pending"
    READY = "ready"
    AWAITING_DECISION = "awaiting_decision"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_WARNINGS = "succeeded_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    CACHED = "cached"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        """True for states from which the task never moves on without an explicit retry."""
        return self in _TERMINAL


_TERMINAL = frozenset(
    {
        TaskState.SUCCEEDED,
        TaskState.SUCCEEDED_WITH_WARNINGS,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.SKIPPED,
        TaskState.CACHED,
    }
)
