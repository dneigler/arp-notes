"""storage.s3: S3Storage key layout, idempotent put, chunked reads, per-user bytes, tested with moto
(C2b, ga-mxal.26)."""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Iterator

import boto3
import pytest
from arp_notes.ports import Storage
from arp_notes.storage.s3 import CHUNK_BYTES, S3Storage
from moto import mock_aws

BUCKET = "arpn-test"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def s3() -> Iterator[object]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def storage(s3: object) -> S3Storage:
    return S3Storage(BUCKET, "notes/", client=s3)


def put(storage: S3Storage, user_id: str, data: bytes, mime: str = "image/png") -> str:
    return storage.put(user_id, digest(data), io.BytesIO(data), mime=mime, size_bytes=len(data))


def read(storage: S3Storage, user_id: str, data: bytes) -> bytes:
    return b"".join(storage.open(user_id, digest(data)))


def keys(s3: object) -> list[str]:
    listing = s3.list_objects_v2(Bucket=BUCKET)  # type: ignore[attr-defined]
    return sorted(o["Key"] for o in listing.get("Contents", []))


def test_s3_storage_is_a_storage(storage: S3Storage) -> None:
    assert isinstance(storage, Storage)


def test_module_imports_without_boto3_until_a_client_is_needed() -> None:
    storage = S3Storage(BUCKET)  # no client, no boto3 call
    assert storage._client is None  # noqa: SLF001


def test_key_is_prefix_hashed_user_sha_fanout_and_is_the_locator(
    storage: S3Storage, s3: object
) -> None:
    data = b"layout"
    locator = put(storage, "dave@example.com", data)
    owner = hashlib.sha256(b"dave@example.com").hexdigest()[:16]
    sha = digest(data)
    assert locator == f"notes/{owner}/{sha[:2]}/{sha}"
    assert keys(s3) == [locator]
    assert "dave" not in locator  # no user text in keys


def test_empty_prefix_is_allowed(s3: object) -> None:
    storage = S3Storage(BUCKET, client=s3)
    locator = put(storage, "u1", b"x")
    assert locator == f"{hashlib.sha256(b'u1').hexdigest()[:16]}/{digest(b'x')[:2]}/{digest(b'x')}"


def test_put_sets_the_content_type(storage: S3Storage, s3: object) -> None:
    locator = put(storage, "u1", b"img", mime="image/webp")
    head = s3.head_object(Bucket=BUCKET, Key=locator)  # type: ignore[attr-defined]
    assert head["ContentType"] == "image/webp"
    assert head["ContentLength"] == 3


def test_round_trip_and_chunk_bound(storage: S3Storage) -> None:
    data = os.urandom(2 * CHUNK_BYTES + 17)
    put(storage, "u1", data)
    chunks = list(storage.open("u1", digest(data)))
    assert b"".join(chunks) == data
    assert all(isinstance(c, bytes) and 0 < len(c) <= 1024 * 1024 for c in chunks)
    assert len(chunks) >= 3


def test_empty_blob_round_trips(storage: S3Storage) -> None:
    put(storage, "u1", b"")
    assert read(storage, "u1", b"") == b""


def test_put_is_idempotent_and_does_not_read_the_stream_the_second_time(
    storage: S3Storage, s3: object
) -> None:
    data = b"same bytes"
    first = put(storage, "u1", data)
    stream = io.BytesIO(data)
    again = storage.put("u1", digest(data), stream, mime="image/png", size_bytes=len(data))
    assert again == first
    assert stream.tell() == 0
    assert keys(s3) == [first]


def test_put_with_the_wrong_length_leaves_no_object(storage: S3Storage, s3: object) -> None:
    data = b"twelve bytes"
    for size in (len(data) - 1, len(data) + 1):
        with pytest.raises(ValueError, match="expected"):
            storage.put("u1", digest(data), io.BytesIO(data), mime="image/png", size_bytes=size)
    assert keys(s3) == []


def test_absent_blob_raises_lookup_error_when_open_is_called(storage: S3Storage) -> None:
    with pytest.raises(LookupError):
        storage.open("u1", digest(b"never stored"))  # not on first next()


def test_delete_removes_the_object_and_is_idempotent(storage: S3Storage, s3: object) -> None:
    data = b"to delete"
    put(storage, "u1", data)
    storage.delete("u1", digest(data))
    assert keys(s3) == []
    with pytest.raises(LookupError):
        storage.open("u1", digest(data))
    storage.delete("u1", digest(data))  # absent is not an error


def test_two_users_with_the_same_sha256_get_separate_objects(
    storage: S3Storage, s3: object
) -> None:
    data = b"shared bytes"
    a = put(storage, "u1", data)
    b = put(storage, "u2", data)
    assert a != b
    assert keys(s3) == sorted([a, b])
    assert read(storage, "u1", data) == read(storage, "u2", data) == data

    storage.delete("u1", digest(data))
    with pytest.raises(LookupError):
        storage.open("u1", digest(data))
    assert read(storage, "u2", data) == data  # deleting one copy leaves the other


def test_one_user_cannot_read_another_users_bytes(storage: S3Storage) -> None:
    put(storage, "u1", b"private")
    with pytest.raises(LookupError):
        storage.open("u2", digest(b"private"))


@pytest.mark.parametrize("bad", ["", "ABC", "../etc/passwd", "g" * 64, digest(b"x").upper()])
def test_a_malformed_sha256_is_refused_before_any_request(bad: str) -> None:
    storage = S3Storage(BUCKET)  # no client: any request would try to build one
    with pytest.raises(ValueError):
        storage.put("u1", bad, io.BytesIO(b""), mime="image/png", size_bytes=0)
    with pytest.raises(ValueError):
        storage.open("u1", bad)
    with pytest.raises(ValueError):
        storage.delete("u1", bad)
    assert storage._client is None  # noqa: SLF001


def test_errors_other_than_missing_are_not_swallowed(storage: S3Storage) -> None:
    broken = S3Storage("no-such-bucket", client=storage.client)
    with pytest.raises(Exception) as caught:
        broken.open("u1", digest(b"x"))
    assert not isinstance(caught.value, LookupError)  # NoSuchBucket is a real fault, not a 404
