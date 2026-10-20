# Choosing a storage backend

Attachment bytes live behind the `Storage` port (`arp_notes.ports.Storage`, K§12.1). The core keeps
a metadata registry (`blobs`) and never assumes where the bytes are. Three reference adapters ship
in `arp-notes-core`; a host can also supply its own.

```python
class Storage(Protocol):
    def put(self, user_id, sha256, stream, *, mime, size_bytes) -> str: ...  # returns the locator
    def open(self, user_id, sha256) -> Iterator[bytes]: ...  # chunks <= 1 MiB
    def delete(self, user_id, sha256) -> None: ...  # idempotent
```

Rules every adapter follows:

- **Bytes are per user.** Two users who upload the same file each get a copy; the key is
  `(user_id, sha256)`, matching `blobs UNIQUE(user_id, sha256)`.
- **The core verifies before it stores.** sha256 and size are checked against the upload ticket
  before `put` is called, so adapters do not re-hash.
- **`put` is idempotent.** Existing bytes for `(user_id, sha256)` are left alone and the stream is
  not read.
- **`open` fails eagerly.** A missing blob raises `LookupError` from the `open()` call itself, not
  from the first `next()`, so the router can answer 404 before it starts a response.
- **`delete` is idempotent.** Absent is not an error.
- **The locator is informational.** The core stores it in `blobs.storage_path` and never parses it.

## Which backend?

| | `DiskStorage` | `PostgresStorage` | `S3Storage` |
|---|---|---|---|
| Import | `arp_notes.storage.disk` | `arp_notes.storage.postgres` | `arp_notes.storage.s3` |
| Install | core | core | `pip install arp-notes-core[s3]` (boto3) |
| Bytes live in | a directory on a persistent volume | a table in the host's Postgres | a bucket |
| Locator | `<h>/<sha[:2]>/<sha>` | the sha256 | `<prefix><h>/<sha[:2]>/<sha>` |
| Backup | back up the volume separately | rides along with the database (see below) | bucket versioning / replication |
| Transactional with the registry | no | yes (same database) | no |
| Good for | one host, one volume, no extra moving parts | a small, single-user or few-user deployment that wants one datastore to back up | anything that outgrows a database or a volume; multi-instance hosts |

`h` is `sha256(user_id).hexdigest()[:16]`, so no user text ever reaches a path or key.

**Start with Postgres if the host already runs it and the volume is small** (one person's
screenshots, megabytes). **Start with disk if you have a persistent volume and want no database
load from blob reads.** **Use S3 when you have more than one app instance, or you are past the exit
criteria below.** Switching later is a swap of the adapter in `HostConfig`; the core, the protocol
and the clients do not change. Moving existing bytes is the host's job: read each blob from the old
adapter and `put` it into the new one, then update `blobs.storage_path`.

## Postgres (`PostgresStorage`)

```python
from arp_notes.storage.postgres import PostgresStorage

# db is the host's Db port: the adapter opens no connections of its own
storage = PostgresStorage(db, table="note_blobs")
```

The table is host-owned: the core DDL (`arp_notes.schema.ddl()`) does not create it, because other
hosts choose another backend. Apply `PostgresStorage.ddl(table)` in the host's own migration (PT:
migration 043, next to the core DDL). It is idempotent (`IF NOT EXISTS`), and for the default name
it is the ADR A.1 PT-delta block:

```sql
CREATE TABLE IF NOT EXISTS note_blobs (
    user_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,                       -- matches blobs.sha256
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    bytes BYTEA NOT NULL,                       -- served by chunked reads only (D16)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, sha256)
);
```

How it behaves:

- **`put`** inserts `(user_id, sha256, mime, size_bytes, bytes)` with `ON CONFLICT DO NOTHING` and
  returns the sha256 as the locator. It buffers the blob once, because one INSERT carries one
  value, so it is bounded: `max_bytes` defaults to the 25 MB attachment cap
  (`Policy.max_attachment_bytes`), and the stream is never read past the declared size.
- **`open`** reads with `substring(bytes from <offset> for <n>)`, one statement per **256 KB** chunk
  (`chunk_bytes`, at most 1 MiB), so a read never holds more than one chunk. A 5 MB blob is 20
  statements and 20 chunks.
- **`delete`** is a plain `DELETE`; a refcount GC sweep is the host's maintenance job.
- **The table name is spliced into SQL**, so it must be a bare or schema-qualified identifier
  (`note_blobs`, `app.note_blobs`). Anything else raises `ValueError`.

### Operating it

**Backups: keep the blobs out of routine logical dumps and snapshot them separately.**

```sh
# routine logical dump: schema for note_blobs, but none of its rows
pg_dump --exclude-table-data=note_blobs "$DATABASE_URL" > app.sql

# separate snapshot of the blob bytes (run on its own schedule)
pg_dump --data-only --table=note_blobs "$DATABASE_URL" | gzip > note_blobs.sql.gz
```

Restore both for a full recovery. A restore of `app.sql` alone leaves the `blobs` registry pointing
at empty `note_blobs`, and every `open` answers 404 until the snapshot is loaded.

**VACUUM after blob GC.** BYTEA values over about 2 KB are TOASTed out of line, and deleting rows
leaves TOAST bloat behind. After a GC sweep that deletes blobs, run `VACUUM note_blobs` (it cannot
run inside a transaction, so it is not part of `delete`).

**Image bytes do not compress, and slicing a compressed TOAST value is slow.** Postgres only
slices a TOAST value cheaply when it is stored uncompressed (`EXTERNAL`). Common image formats
(PNG, JPEG, WebP, AVIF) are already compressed, so Postgres keeps them uncompressed anyway. If a
host stores compressible bytes (SVG, PDF, text), set the column to external storage so each chunk
read is a seek rather than a decompress-from-the-start:

```sql
ALTER TABLE note_blobs ALTER COLUMN bytes SET STORAGE EXTERNAL;
```

### When to leave Postgres: the D16 exit criteria

Switch the host's adapter to the disk-volume or S3 Storage adapter when any of these holds:

- total blob bytes exceed **1–2 GB**;
- `pg_dump`/restore time is visibly degraded by blobs;
- serving latency or DB memory pressure is attributable to blob reads;
- real multi-user traffic arrives.

The Storage port makes the swap invisible to the core, the protocol and the clients.

## Disk (`DiskStorage`)

```python
from arp_notes.storage.disk import DiskStorage

storage = DiskStorage("/var/lib/app/note-blobs")
```

Layout `<root>/<h>/<sha256[:2]>/<sha256>`. A write goes to a temp file in the target directory and
is renamed into place, so a reader never sees a partial blob. The root must be a **persistent
volume**: a container's own filesystem loses the bytes on the next deploy while the `blobs` registry
still lists them. Back the directory up on its own schedule.

## S3 (`S3Storage`)

```sh
pip install "arp-notes-core[s3]"
```

```python
import boto3
from arp_notes.storage.s3 import S3Storage

storage = S3Storage("my-bucket", prefix="notes/", client=boto3.client("s3"))
```

Key: `<prefix><h>/<sha256[:2]>/<sha256>`. Pass `client` to reuse the host's own boto3 client
(credentials, region, a custom `endpoint_url` for MinIO or R2); without one the adapter builds
`boto3.client("s3")` from the standard credential chain on first use. boto3 is imported lazily, so
`arp_notes.storage.s3` imports without the extra and only a call that needs a client requires it.

- **`put`** checks the key with `HEAD` first and does nothing when it exists, then uploads with
  `upload_fileobj` (chunked, multipart for large bodies, content type set from `mime`). If the byte
  count differs from `size_bytes`, the object is deleted and `ValueError` is raised.
- **`open`** streams the object in chunks of at most 1 MiB. A missing key raises `LookupError`;
  any other error (no such bucket, access denied) propagates, because it is a fault and not a 404.
- **`delete`** relies on S3 treating a delete of an absent key as success.
- Bucket policy, encryption, lifecycle and versioning are the host's to configure. The adapter
  needs `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` and `s3:ListBucket` (the last so a `HEAD`
  on a missing key answers 404 instead of 403).

## Writing your own adapter

Implement the three methods above and run the same checks the reference adapters pass:
a round trip in bounded chunks, an idempotent `put`, an eager `LookupError` from `open`, an
idempotent `delete`, and two users with the same sha256 getting separate bytes. See
`packages/core/tests/test_storage_{disk,postgres,s3}.py`.
