"""Content-addressed artifact store."""

from __future__ import annotations

import hashlib
import io
import os
import stat
from pathlib import Path

import pytest

from caddsuite.storage.artifacts import ArtifactIntegrityError, ArtifactStore


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


def test_put_bytes_is_content_addressed_and_read_only(store: ArtifactStore) -> None:
    data = b"center_x = 4.701\ncenter_y = 12.376\ncenter_z = 188.797\n"
    blob = store.put_bytes(data)
    assert blob.sha256 == hashlib.sha256(data).hexdigest()
    assert blob.created
    assert blob.path == store.path_for(blob.sha256)
    assert blob.path.read_bytes() == data
    assert not blob.path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


def test_identical_content_is_stored_once(store: ArtifactStore) -> None:
    first = store.put_bytes(b"same bytes")
    second = store.put_bytes(b"same bytes")
    assert not second.created
    assert first.path == second.path
    assert list(store.iter_hashes()) == [first.sha256]


def test_put_file_streams_large_input(store: ArtifactStore, tmp_path: Path) -> None:
    source = tmp_path / "trajectory.xtc"
    payload = os.urandom(3 * 1024 * 1024 + 17)  # > several chunks, odd size
    source.write_bytes(payload)
    blob = store.put_file(source)
    assert blob.sha256 == hashlib.sha256(payload).hexdigest()
    assert blob.size_bytes == len(payload)
    assert store.verify(blob.sha256)


def test_verify_detects_corruption(store: ArtifactStore) -> None:
    blob = store.put_bytes(b"original")
    blob.path.chmod(0o644)
    blob.path.write_bytes(b"tampered")
    assert not store.verify(blob.sha256)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "ABCDEF" + "0" * 58, "abc", ""])
def test_path_for_rejects_non_digests(store: ArtifactStore, bad: str) -> None:
    with pytest.raises(ValueError, match="sha256"):
        store.path_for(bad)


def test_failed_ingest_leaves_no_temporary_files(store: ArtifactStore) -> None:
    class Exploding(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            raise OSError("disk went away")

    with pytest.raises(OSError, match="disk went away"):
        store._ingest(Exploding(b"x"))
    assert list((store.root / "tmp").iterdir()) == []


def test_existing_blob_with_wrong_size_is_reported(store: ArtifactStore) -> None:
    data = b"payload"
    blob = store.put_bytes(data)
    blob.path.chmod(0o644)
    blob.path.write_bytes(b"payload-plus-garbage")
    with pytest.raises(ArtifactIntegrityError):
        store.put_bytes(data)
