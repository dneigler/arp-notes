"""storage.disk: DiskStorage layout, atomic writes, idempotence, per-user bytes (C2, ga-mxal.9)."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from arp_notes.ports import Storage
from arp_notes.storage.disk import CHUNK_BYTES, DiskStorage


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put(storage: DiskStorage, user_id: str, data: bytes) -> str:
    return storage.put(
        user_id, digest(data), io.BytesIO(data), mime="image/png", size_bytes=len(data)
    )


def read(storage: DiskStorage, user_id: str, data: bytes) -> bytes:
    return b"".join(storage.open(user_id, digest(data)))


def test_disk_storage_is_a_storage(tmp_path: Path) -> None:
    assert isinstance(DiskStorage(tmp_path), Storage)


def test_layout_hashes_the_user_and_fans_out_on_the_sha(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    data = b"layout"
    locator = put(storage, "dave@example.com", data)
    owner = hashlib.sha256(b"dave@example.com").hexdigest()[:16]
    sha = digest(data)
    assert locator == f"{owner}/{sha[:2]}/{sha}"
    assert (tmp_path / locator).read_bytes() == data
    assert "dave" not in locator  # no user text in paths


def test_round_trip_and_chunk_bound(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    data = b"x" * (2 * CHUNK_BYTES + 17)
    put(storage, "u1", data)
    chunks = list(storage.open("u1", digest(data)))
    assert b"".join(chunks) == data
    assert len(chunks) == 3
    assert all(len(chunk) <= 1024 * 1024 for chunk in chunks)


def test_empty_blob_round_trips(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    put(storage, "u1", b"")
    assert read(storage, "u1", b"") == b""


def test_put_is_idempotent_and_writes_nothing_the_second_time(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    data = b"same bytes"
    first = put(storage, "u1", data)
    path = tmp_path / first
    mtime = path.stat().st_mtime_ns
    again = put(storage, "u1", data)
    assert again == first
    assert path.stat().st_mtime_ns == mtime
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no stray temp file


def test_two_users_with_identical_bytes_get_separate_copies(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    data = b"shared bytes"
    a = put(storage, "u1", data)
    b = put(storage, "u2", data)
    assert a != b
    assert read(storage, "u1", data) == read(storage, "u2", data) == data
    storage.delete("u1", digest(data))
    assert read(storage, "u2", data) == data  # deleting one copy leaves the other


def test_open_missing_raises_lookup_error_at_call_time(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    with pytest.raises(LookupError):
        storage.open("u1", digest(b"never stored"))  # not on the first next()


def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    data = b"to delete"
    put(storage, "u1", data)
    storage.delete("u1", digest(data))
    storage.delete("u1", digest(data))
    storage.delete("never-seen", digest(b"nothing"))
    with pytest.raises(LookupError):
        storage.open("u1", digest(data))


def test_a_short_stream_is_refused_and_leaves_nothing_behind(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    data = b"truncated"
    with pytest.raises(ValueError, match="expected"):
        storage.put(
            "u1", digest(data), io.BytesIO(data[:3]), mime="image/png", size_bytes=len(data)
        )
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []  # no blob, no .tmp- file
    with pytest.raises(LookupError):
        storage.open("u1", digest(data))


class ExplodingStream(io.BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(size)
        if not chunk:
            raise OSError("disk went away")
        return chunk


def test_a_failing_stream_never_publishes_a_partial_blob(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)
    data = b"partial"
    with pytest.raises(OSError, match="disk went away"):
        storage.put(
            "u1", digest(data), ExplodingStream(data), mime="image/png", size_bytes=len(data)
        )
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


@pytest.mark.parametrize("bad", ["", "abc", "../" * 22, "A" * 64, "g" * 64])
def test_a_malformed_sha256_never_reaches_the_filesystem(tmp_path: Path, bad: str) -> None:
    storage = DiskStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.put("u1", bad, io.BytesIO(b""), mime="image/png", size_bytes=0)
    with pytest.raises(ValueError):
        storage.open("u1", bad)
    with pytest.raises(ValueError):
        storage.delete("u1", bad)
