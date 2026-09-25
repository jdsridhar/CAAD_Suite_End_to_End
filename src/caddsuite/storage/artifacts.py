"""Content-addressed artifact store (ADR-0005).

How it works
------------
1. Bytes stream into a temporary file *inside the store*, hashed with SHA-256 **while
   copying**. The stored bytes are therefore exactly the hashed bytes, even if the source
   file changes during the copy.
2. The temp file is atomically renamed to ``sha256/<aa>/<bb>/<hash>`` and made read-only.
   Identical content is stored once (deduplication).
3. The database row (``ArtifactRow``) records size, media type, kind and producer. Names
   and roles belong to the *links*, never to the blob.

Why
---
The legacy apps treated "the file exists" as "the work is done", so stale files were
silently reused when inputs changed (audit ARCH-03). With content addressing the name *is*
the content: if the input changes, its hash changes, and caches keyed on it miss correctly.

Learning note
-------------
This is the same idea as git's object store and Nix's store paths.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from caddsuite.storage.models import ArtifactRow

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
CHUNK_BYTES = 1024 * 1024


class BinaryReadable(Protocol):
    """Minimal binary stream accepted by incremental artifact ingestion."""

    def read(self, size: int = -1) -> bytes: ...


class ArtifactIntegrityError(RuntimeError):
    """Stored bytes no longer match their hash (corruption or tampering)."""


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    size_bytes: int
    path: Path
    created: bool  # False when identical content was already present


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._blobs = root / "sha256"
        self._tmp = root / "tmp"
        self._blobs.mkdir(parents=True, exist_ok=True)
        self._tmp.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ addressing
    def path_for(self, sha256: str) -> Path:
        """Location of a blob. Rejects anything that is not a 64-hex digest, so no caller
        can smuggle a path such as ``../../etc`` through a hash parameter."""
        if not _HEX64.match(sha256):
            raise ValueError(f"not a sha256 hex digest: {sha256!r}")
        return self._blobs / sha256[:2] / sha256[2:4] / sha256

    def exists(self, sha256: str) -> bool:
        return self.path_for(sha256).is_file()

    # --------------------------------------------------------------------- ingest
    def put_bytes(self, data: bytes) -> StoredBlob:
        return self._ingest(io.BytesIO(data))

    def put_file(self, source: Path) -> StoredBlob:
        with source.open("rb") as stream:
            return self.put_stream(stream)

    def put_stream(self, stream: BinaryReadable) -> StoredBlob:
        """Ingest a seeked binary stream without loading its contents into memory."""
        return self._ingest(stream)

    def _ingest(self, stream: BinaryReadable) -> StoredBlob:
        digest = hashlib.sha256()
        size = 0
        fd, tmp_name = tempfile.mkstemp(dir=self._tmp, prefix="ingest-")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := stream.read(CHUNK_BYTES):
                    digest.update(chunk)
                    out.write(chunk)
                    size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            sha = digest.hexdigest()
            final = self.path_for(sha)
            if final.exists():
                if final.stat().st_size != size:
                    raise ArtifactIntegrityError(
                        f"existing blob {sha} has size {final.stat().st_size}, expected {size}"
                    )
                tmp.unlink()
                return StoredBlob(sha, size, final, created=False)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(tmp, 0o444)
            os.replace(tmp, final)  # atomic on the same filesystem
            return StoredBlob(sha, size, final, created=True)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    # ----------------------------------------------------------------------- read
    def open(self, sha256: str) -> BinaryIO:
        return self.path_for(sha256).open("rb")

    def verify(self, sha256: str) -> bool:
        """Re-hash a stored blob; True if it still matches its address."""
        digest = hashlib.sha256()
        with self.open(sha256) as stream:
            while chunk := stream.read(CHUNK_BYTES):
                digest.update(chunk)
        return digest.hexdigest() == sha256

    def iter_hashes(self) -> Iterator[str]:
        for path in sorted(self._blobs.glob("*/*/*")):
            if _HEX64.match(path.name):
                yield path.name


def register_blob(
    session: Session,
    blob: StoredBlob,
    *,
    kind: str,
    media_type: str,
    original_name: str | None = None,
    producer_attempt_id: str | None = None,
) -> ArtifactRow:
    """Record a stored blob in the database (idempotent on its sha256)."""
    existing = session.scalar(select(ArtifactRow).where(ArtifactRow.sha256 == blob.sha256))
    if existing is not None:
        if existing.size_bytes != blob.size_bytes:
            raise ArtifactIntegrityError(f"size mismatch for already-registered {blob.sha256}")
        return existing
    row = ArtifactRow(
        sha256=blob.sha256,
        size_bytes=blob.size_bytes,
        media_type=media_type,
        kind=kind,
        original_name=original_name,
        producer_attempt_id=producer_attempt_id,
    )
    session.add(row)
    session.flush()
    return row
