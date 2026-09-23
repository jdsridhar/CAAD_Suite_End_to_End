"""Base classes and shared value types for all normalized contracts.

Key ideas (ADR-0004)
--------------------
* ``ContractModel`` is frozen (results are immutable once produced) and forbids unknown
  fields, so a typo in an adapter's output fails loudly instead of being dropped.
* ``VersionedContract`` stamps every payload with ``schema_version = "<name>/<major>.<minor>"``.
  Stored payloads from an older *major* version are migrated by registered **upcasters**
  when read (``load_contract``). This fixes the silent schema drift seen in the legacy
  DFT ``result.json`` files (ARCHITECTURE_AUDIT ARCH-07).

Learning note
-------------
An *upcaster* is a small pure function ``dict -> dict`` that turns version N of a payload
into version N+1. Chaining upcasters lets a reader built today open data written years
ago, a common pattern in event-sourced systems and long-lived scientific data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any, Final

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import ULIDStr

# ----------------------------------------------------------------------- value types
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
PHValue = Annotated[float, Field(ge=0, le=14)]
Vector3 = tuple[float, float, float]
PositiveVector3 = tuple[PositiveFloat, PositiveFloat, PositiveFloat]

CompoundAccession = Annotated[str, StringConstraints(pattern=r"^CMP\d{4,}$")]
TargetAccession = Annotated[str, StringConstraints(pattern=r"^TGT\d{3,}$")]


DockingAccession = Annotated[str, StringConstraints(pattern=r"^CMP\d{4,}_DOCK_\d{3,}$")]
PoseAccession = Annotated[str, StringConstraints(pattern=r"^CMP\d{4,}_POSE_\d{3,}$")]
MDAccession = Annotated[str, StringConstraints(pattern=r"^CMP\d{4,}_MD_\d{3,}$")]
BindingEnergyAccession = Annotated[str, StringConstraints(pattern=r"^CMP\d{4,}_MMPBSA_\d{3,}$")]
QMAccession = Annotated[str, StringConstraints(pattern=r"^CMP\d{4,}_QM_\d{3,}$")]
ADMETAccession = Annotated[str, StringConstraints(pattern=r"^CMP\d{4,}_ADMET_\d{3,}$")]

#: Stable, dotted, upper-case codes used by validation issues and error records,
#: e.g. ``MMGBSA.TEMPERATURE_MISMATCH`` or ``QM.SCF_NOT_CONVERGED``.
CODE_PATTERN: Final[str] = r"^[A-Z][A-Z0-9_]*(\.[A-Z][A-Z0-9_]*)+$"
Code = Annotated[str, StringConstraints(pattern=CODE_PATTERN)]


# ------------------------------------------------------------------------ base models
class ContractModel(BaseModel):
    """Immutable, strict base for every contract and value object."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class SoftwareRef(ContractModel):
    """A piece of software that took part in producing a result (a provenance *agent*)."""

    name: NonEmptyStr
    version: NonEmptyStr  # use "unknown" explicitly rather than leaving it empty
    kind: SoftwareKind
    license_class: LicenseClass = LicenseClass.UNKNOWN
    environment_id: ULIDStr | None = None


class ArtifactRef(ContractModel):
    """Reference to a content-addressed artifact plus the role it plays for this result."""

    artifact_id: ULIDStr
    role: NonEmptyStr
    sha256: Sha256Hex | None = None


class EntityRef(ContractModel):
    """Polymorphic reference to another platform entity (e.g. a pose or a conformer)."""

    kind: NonEmptyStr
    id: ULIDStr
    accession: str | None = None


# --------------------------------------------------------------- versioned contracts
_REGISTRY: dict[str, type[VersionedContract]] = {}
Upcaster = Callable[[dict[str, Any]], dict[str, Any]]
_UPCASTERS: dict[tuple[str, int], Upcaster] = {}


def _split_version(schema_version: str) -> tuple[str, int, int]:
    try:
        name, version = schema_version.split("/", 1)
        major_s, minor_s = version.split(".", 1)
        return name, int(major_s), int(minor_s)
    except ValueError as exc:
        raise ValueError(
            f"schema_version must look like '<name>/<major>.<minor>', got {schema_version!r}"
        ) from exc


class VersionedContract(ContractModel):
    """A top-level payload that is stored, exported and versioned.

    Each concrete contract declares exactly one line of version information, e.g.
    ``schema_version: str = "compound/1.0"``. The default is the single source of truth
    for the contract's name and current version. It is written into every new payload
    and shows up in the JSON Schema.
    """

    schema_version: str

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        default = cls.model_fields["schema_version"].default
        if not isinstance(default, str):
            return  # abstract intermediate class without a concrete version
        name, _major, _minor = _split_version(default)
        existing = _REGISTRY.get(name)
        if existing is not None and existing.__qualname__ != cls.__qualname__:
            raise TypeError(f"duplicate contract name {name!r}: {existing} vs {cls}")
        _REGISTRY[name] = cls

    @classmethod
    def schema_id(cls) -> str:
        """The value written into ``schema_version`` for newly created payloads."""
        default = cls.model_fields["schema_version"].default
        if not isinstance(default, str):
            raise TypeError(f"{cls.__name__} does not declare a concrete schema_version")
        return default

    @classmethod
    def schema_name(cls) -> str:
        return _split_version(cls.schema_id())[0]

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, value: str) -> str:
        name, major, _minor = _split_version(value)
        cur_name, cur_major, _ = _split_version(cls.schema_id())
        if name != cur_name or major != cur_major:
            raise ValueError(
                f"payload {value!r} is not readable as {cls.schema_id()!r}; "
                "use load_contract() to apply upcasters"
            )
        return value


def register_upcaster(name: str, from_major: int) -> Callable[[Upcaster], Upcaster]:
    """Register a function migrating payloads of ``name`` from major N to N+1."""

    def decorator(func: Upcaster) -> Upcaster:
        key = (name, from_major)
        if key in _UPCASTERS:
            raise ValueError(f"upcaster already registered for {key}")
        _UPCASTERS[key] = func
        return func

    return decorator


def contract_registry() -> Mapping[str, type[VersionedContract]]:
    """Read-only view of all registered contract classes, keyed by schema name."""
    return dict(_REGISTRY)


def load_contract(payload: Mapping[str, Any]) -> VersionedContract:
    """Validate a stored payload, upcasting older major versions first."""
    if "schema_version" not in payload:
        raise ValueError("payload has no schema_version; cannot determine its contract")
    name, major, minor = _split_version(str(payload["schema_version"]))
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown contract {name!r}")
    _, current_major, _ = _split_version(cls.schema_id())
    if major > current_major:
        raise ValueError(
            f"{name} payload is version {major}.{minor}, newer than this platform "
            f"understands ({cls.schema_id()}); upgrade caddsuite"
        )
    data = dict(payload)
    while major < current_major:
        upcaster = _UPCASTERS.get((name, major))
        if upcaster is None:
            raise ValueError(f"no upcaster registered for {name} major version {major}")
        data = upcaster(data)
        major += 1
        data["schema_version"] = f"{name}/{major}.0"
    return cls.model_validate(data)
