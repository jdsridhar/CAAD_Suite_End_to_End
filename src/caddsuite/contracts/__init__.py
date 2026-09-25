"""Normalized, versioned result contracts (docs/architecture/DOMAIN_MODEL.md).

Importing this package registers every contract class, so ``load_contract`` and
``contract_registry`` see all of them.
"""

from caddsuite.contracts import (  # noqa: F401  (imported for registration side effects)
    analysis,
    complex,
    docking,
    evidence,
    execution,
    legacy,
    md,
    properties,
    qm,
    registry,
    reporting,
    structure,
    system,
    visualization,
)
from caddsuite.contracts.base import (
    ArtifactRef,
    ContractModel,
    EntityRef,
    SoftwareRef,
    VersionedContract,
    contract_registry,
    load_contract,
    register_upcaster,
)

__all__ = [
    "ArtifactRef",
    "ContractModel",
    "EntityRef",
    "SoftwareRef",
    "VersionedContract",
    "contract_registry",
    "load_contract",
    "register_upcaster",
]
