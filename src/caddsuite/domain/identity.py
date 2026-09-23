"""Identity: machine IDs (ULIDs) and human-readable accessions.

Why this module exists
----------------------
The legacy apps identified things by file and directory names: ``<name>__<PDB>`` in
docking, free-text project names in MD, ``batch_<name>`` in DFT. Nothing linked a pose to
the MD system built from it (ARCHITECTURE_AUDIT ARCH-02). The platform separates:

* **ULIDs**: immutable primary keys. 128 bits: a 48-bit millisecond timestamp plus 80
  random bits, encoded as 26 Crockford-base32 characters. They sort by creation time,
  which keeps database indexes and logs readable, and need no central coordination.
* **Accessions**: labels for humans, following the convention in the brief
  (``CMP0001``, ``CMP0001_DOCK_001``, ``CMP0001_POSE_003``, ``RUN-20260923-001``).
  They are allocated per project by the storage layer and are *never* used as foreign keys.

Learning note
-------------
Separating *identity* (a stable key) from *naming* (something people read) is a classic
data-modelling rule. Renaming a compound must never break the provenance graph.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Annotated, Final

from pydantic import StringConstraints

# --------------------------------------------------------------------------------- ULID
_CROCKFORD: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE: Final[dict[str, int]] = {ch: i for i, ch in enumerate(_CROCKFORD)}
ULID_PATTERN: Final[str] = r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"
_ULID_RE: Final[re.Pattern[str]] = re.compile(ULID_PATTERN)
_MAX_TIMESTAMP_MS: Final[int] = 2**48 - 1

#: Pydantic-compatible type for ULID-valued fields.
ULIDStr = Annotated[str, StringConstraints(pattern=ULID_PATTERN)]


def new_ulid(timestamp_ms: int | None = None, randomness: bytes | None = None) -> str:
    """Return a new ULID string.

    ``timestamp_ms`` and ``randomness`` exist for deterministic tests. In normal use both
    are left as ``None`` (current time, 80 bits from ``os.urandom``).
    """
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ts <= _MAX_TIMESTAMP_MS:
        raise ValueError(f"ULID timestamp out of range: {ts}")
    rnd = os.urandom(10) if randomness is None else randomness
    if len(rnd) != 10:
        raise ValueError("ULID randomness must be exactly 10 bytes")
    value = (ts << 80) | int.from_bytes(rnd, "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def is_ulid(text: str) -> bool:
    """True if ``text`` is a canonical (upper-case) ULID."""
    return bool(_ULID_RE.match(text))


def ulid_timestamp_ms(ulid: str) -> int:
    """Extract the millisecond timestamp encoded in a ULID."""
    if not is_ulid(ulid):
        raise ValueError(f"not a ULID: {ulid!r}")
    value = 0
    for ch in ulid:
        value = (value << 5) | _DECODE[ch]
    return value >> 80


# ---------------------------------------------------------------------------- accessions
class AccessionKind(StrEnum):
    """Kinds of human-readable accessions. Values are the literal tokens used in labels."""

    COMPOUND = "CMP"
    TARGET = "TGT"
    RUN = "RUN"
    DOCKING = "DOCK"
    POSE = "POSE"
    MD = "MD"
    BINDING_ENERGY = "MMPBSA"
    QM = "QM"
    ADMET = "ADMET"


#: Kinds that are always derived from a compound accession (``CMP0001_<KIND>_001``).
DERIVED_KINDS: Final[frozenset[AccessionKind]] = frozenset(
    {
        AccessionKind.DOCKING,
        AccessionKind.POSE,
        AccessionKind.MD,
        AccessionKind.BINDING_ENERGY,
        AccessionKind.QM,
        AccessionKind.ADMET,
    }
)

_COMPOUND_RE: Final[re.Pattern[str]] = re.compile(r"^CMP(\d{4,})$")
_TARGET_RE: Final[re.Pattern[str]] = re.compile(r"^TGT(\d{3,})$")
_RUN_RE: Final[re.Pattern[str]] = re.compile(r"^RUN-(\d{8})-(\d{3,})$")
_DERIVED_RE: Final[re.Pattern[str]] = re.compile(
    r"^(CMP\d{4,})_(DOCK|POSE|MD|MMPBSA|QM|ADMET)_(\d{3,})$"
)


@dataclass(frozen=True)
class ParsedAccession:
    """Structured form of an accession label."""

    kind: AccessionKind
    number: int
    parent: str | None = None  # the compound accession, for derived kinds
    run_date: date | None = None  # for RUN accessions


def _check_number(number: int) -> None:
    if number < 1:
        raise ValueError(f"accession numbers start at 1, got {number}")


def compound_accession(number: int) -> str:
    """``CMP0001`` style label (zero-padded to 4 digits, grows beyond 9999)."""
    _check_number(number)
    return f"CMP{number:04d}"


def target_accession(number: int) -> str:
    """``TGT001`` style label."""
    _check_number(number)
    return f"TGT{number:03d}"


def run_accession(run_date: date, number: int) -> str:
    """``RUN-20260923-001`` style label (sequence restarts each day)."""
    _check_number(number)
    return f"RUN-{run_date:%Y%m%d}-{number:03d}"


def derived_accession(compound: str, kind: AccessionKind, number: int) -> str:
    """``CMP0001_DOCK_001`` style label for a result derived from a compound."""
    _check_number(number)
    if kind not in DERIVED_KINDS:
        raise ValueError(f"{kind} is not a compound-derived accession kind")
    if not _COMPOUND_RE.match(compound):
        raise ValueError(f"parent must be a compound accession, got {compound!r}")
    return f"{compound}_{kind.value}_{number:03d}"


def parse_accession(label: str) -> ParsedAccession:
    """Parse any accession label; raises ``ValueError`` for unknown formats."""
    if m := _COMPOUND_RE.match(label):
        return ParsedAccession(AccessionKind.COMPOUND, int(m.group(1)))
    if m := _TARGET_RE.match(label):
        return ParsedAccession(AccessionKind.TARGET, int(m.group(1)))
    if m := _RUN_RE.match(label):
        d = m.group(1)
        return ParsedAccession(
            AccessionKind.RUN,
            int(m.group(2)),
            run_date=date(int(d[:4]), int(d[4:6]), int(d[6:])),
        )
    if m := _DERIVED_RE.match(label):
        return ParsedAccession(AccessionKind(m.group(2)), int(m.group(3)), parent=m.group(1))
    raise ValueError(f"unrecognized accession: {label!r}")
