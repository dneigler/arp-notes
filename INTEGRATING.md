# Integrating arp-notes into a FastAPI + React app

One session, five steps. **Done means the conformance kit is green**, not that the code reads well.
Everything below is a working snippet; `examples/fastapi-minimal/app.py` is all of it in one file
that passes the kit. Wire contract: [PROTOCOL.md](PROTOCOL.md). JSON Schemas:
`packages/core/arp_notes/schemas/*.json`. Rules the core keeps: no ORM, no app globals, no users
table, no connection of its own. You supply ports; it never reaches past them.

1. Install. 2. `arp-notes init`. 3. Fill in the ports. 4. Mount routes and MCP tools. 5. Run the kit.

## 1 · Install

Pin one tag for everything (`v0.1.0` below; use the tag your team pins). No registry in v0.1.

```bash
uv add "arp-notes-core @ git+https://github.com/dneigler/arp-notes@v0.1.0#subdirectory=packages/core"
uv add --dev "arp-notes-conformance @ git+https://github.com/dneigler/arp-notes@v0.1.0#subdirectory=packages/conformance"
uv add --dev "arp-notes @ git+https://github.com/dneigler/arp-notes@v0.1.0#subdirectory=packages/cli"
# React UI: the tarball attached to that tag's GitHub release (npm cannot install a git subdirectory)
npm install https://github.com/dneigler/arp-notes/releases/download/v0.1.0/arpinator-notes-ui-0.1.0.tgz
```

`@arpinator/notes-ui` wants `react` (18+) and the CodeMirror 6 packages as peers
(`@codemirror/{state,view,commands,language,autocomplete}`, `@lezer/markdown`). Core needs Python
3.12, FastAPI and Postgres (the DDL uses JSONB and SERIAL).

## 2 · Scaffold

```bash
uv run arp-notes init --host fastapi            # from the app's root; --dry-run shows the plan
```

It writes, and never overwrites without `--force`: `<package>/arp_notes_host.py` (port stubs marked
`TODO(arp-notes)`, `mount_notes`, `register_notes_mcp`), the SQL copies in your migrations folder
(`--migration-number 43` names them `043_notes.sql`, `044_...`) and
`tests/test_arp_notes_conformance.py` (drift test + the kit). `--package`, `--module`,
`--migrations-dir`, `--tests-dir` override what it detected. After a version bump,
`arp-notes init --host fastapi --only migrations` copies the new SQL and touches nothing else.

## 3 · The HostConfig: one object, every port

`HostConfig(db, principal, storage, signer, schemes, policy, judge=None, hooks=None, hygiene=None)`
is built once at startup, so no port is bound to a user: **every method that touches one user's data
takes `user_id` first**. `build_host_config()` in the scaffold is where it is assembled.

**db** (`Db`): raw SQL, `%s` placeholders, one dict per row, `transaction()` commits on a clean
exit and rolls back on an exception. Routes run in FastAPI's threadpool, so keep it thread-safe.

```python
import threading
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row


class HostDb:
    def __init__(self, dsn: str) -> None:
        self._dsn, self._local = dsn, threading.local()

    def _open(self):
        conn = psycopg.connect(self._dsn, autocommit=True)
        conn.row_factory = dict_row  # rows come back as dicts
        return conn

    @contextmanager
    def _conn(self):
        if getattr(self._local, "conn", None) is not None:  # inside transaction()
            yield self._local.conn
        else:
            with self._open() as conn:
                yield conn

    def run(self, sql, params=()):
        with self._conn() as conn:
            cur = conn.execute(sql, tuple(params) or None)
            return list(cur.fetchall()) if cur.description else []

    @contextmanager
    def transaction(self):
        if getattr(self._local, "conn", None) is not None:  # nested: a savepoint
            with self._local.conn.transaction():
                yield self
            return
        with self._open() as conn:
            self._local.conn = conn
            try:
                with conn.transaction():
                    yield self
            finally:
                self._local.conn = None
```

An app with a pool, psycopg2 or SQLAlchemy wraps its own: `run` executes `sql` with `params` and
returns `[dict, ...]` (SQLAlchemy: `conn.exec_driver_sql(sql, tuple(params))` then
`[dict(r._mapping) for r in result]` when `result.returns_rows`).

**principal** (`Principal`): `current_user_id(request) -> str`; raise `HTTPException(401)` when
nobody is signed in. Decode the token the way your auth dependency does.

```python
import jwt
from fastapi import HTTPException, Request


class HostPrincipal:
    def current_user_id(self, request: Request) -> str:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        try:
            return str(jwt.decode(token, SESSION_SECRET, algorithms=["HS256"])["sub"])
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="sign in") from None
```

**storage** (`Storage`): attachment bytes, keyed by `(user_id, sha256)`; `put` is idempotent,
`open` yields chunks of at most 1 MiB and raises `LookupError` when absent, `delete` is
idempotent. The core hashes before it calls `put`. Three adapters ship:

```python
from arp_notes.storage.disk import DiskStorage
from arp_notes.storage.postgres import PostgresStorage
from arp_notes.storage.s3 import S3Storage  # needs boto3

storage = DiskStorage("/var/lib/myapp/notes-blobs")  # one machine with a persistent disk
storage = S3Storage("my-bucket", "notes/")  # prefix; boto3.client("s3") unless client=...
storage = PostgresStorage(db, table="note_blobs")  # no disk and no S3
```

`PostgresStorage` keeps bytes in a table **you** create: put `PostgresStorage.ddl("note_blobs")`
into one of your migrations (the core's DDL does not include it). A custom backend implements the
three methods above.

**signer** (`Signer`): `secret` and `ttl_s` for the expiring attachment URLs (an hour).

```python
class HostSigner:
    ttl_s = 3600

    @property
    def secret(self) -> str:
        return SESSION_SECRET
```

**schemes** (`LinkSchemes`): what a note's passages can link to. One object per scheme, each with a
`prefix` and `entity_types`. Chips look like `[@Title](app://venue/42)`; `entity_id` is an int.

```python
class VenueLinks:
    prefix = "app"
    entity_types = ("venue", "show")

    def resolve(self, user_id, entity_type, entity_id):
        """-> {"title", "url", "preview"?} or None (missing, or not this user's: chip says not found)"""
        row = find_venue(user_id, entity_id)
        return {"title": row.name, "url": f"/venues/{row.id}"} if row else None

    def search(self, user_id, q, *, entity_types=None, limit=20):
        """The [[ autocomplete. Best first. Candidates are dicts."""
        return [
            {"entity_type": "venue", "entity_id": v.id, "entity_label": v.name, "score": 0.5}
            for v in search_venues(user_id, q, limit)
        ]

    def reconcile(self, user_id, spans):
        """One candidate list per span, same order, len(result) == len(spans); [] abstains.
        A span is a dict: text, quote, anchor, kind_hint, context {composer?, opus?, note_title, note_kind}."""
        return [best_venues(user_id, span["text"]) for span in spans]

    # Optional (the core finds them with isinstance):
    def children(self, user_id, entity_type, entity_id):
        """[(entity_type, id), ...]: powers include_children, e.g. a venue's shows."""
        return [("show", s.id) for s in shows_at(user_id, entity_id)]

    def dedupe_key(self, candidate):
        """Equal keys mean the same thing twice; pure, no user_id. None = no opinion."""
        return normalise(candidate["entity_label"])
```

A candidate may also carry `composer_label`, `duplicate_group` and `duplicates` (a cluster you
already collapsed). A wrong-length `reconcile` raises `ValueError` naming the scheme; an `entity_id`
that is not an int does too. Register several schemes in `schemes=[...]`; the core merges them.

**policy** (`Policy`, a dataclass of defaults; `GET /notes/capabilities` reports it and the UI
renders its policy line from that):

```python
from arp_notes.ports import Policy

policy = Policy(
    attachments=True,
    mime_allowlist=["image/png", "image/webp", "application/pdf"],  # None = any type
    max_attachment_bytes=25 * 1024 * 1024,
    max_note_bytes=200 * 1024 * 1024,
    kinds=("masterclass", "lesson", "meeting", "note"),
    source_systems=("obsidian", "llm"),
    export=True,  # leave on: users own their notes
    propose_on_sync="search",  # 'off' | 'search' (candidates, no judge) | 'judge' (K§3)
    llm_enrich=False,  # True also needs hooks.llm_complete (takeaways, action items)
    someday=False,
    hygiene=True,
)
```

The other limits keep their defaults: `max_body_chars` (2 Mi), `max_attachments_per_note` (500),
`manifest_page_size` (50) and `upload_ticket_ttl_s` (15 minutes).

**judge** (optional): picks among ambiguous candidates. Without one the pipeline degrades to search
alone, and sync never depends on it. `Judge.name` feeds `capabilities.judge`.

```python
from arp_notes.judges import ChainJudge, JevChoiceJudge, LlmJudge

judge = JevChoiceJudge(api_key=JEV_API_KEY)  # name "jev-choice"; 2 s timeout
judge = ChainJudge(  # name "jev-choice>haiku"
    JevChoiceJudge(api_key=JEV_API_KEY),
    escalate=LlmJudge(lambda prompt: call_my_llm(prompt), name="haiku"),
    threshold=0.5,  # below this the escalation runs
)
```

`LlmJudge` takes your provider call as `complete(prompt) -> text`; the core imports no provider SDK.

**hooks** (optional): side effects the host performs. Every field may be left `None`.

```python
from arp_notes.ports import Hooks


def on_event(user_id, event_type, entity, summary):
    # entity = {"entity_type": "note", "entity_id": 7, "event": ..., "note_title": ..., "kind": ...,
    #           "origin": ..., "link_count": ..., "attachment_count": ..., + optional keys}
    activity_log.write(
        user_id,
        event_type,
        entity.pop("entity_type"),
        entity.pop("entity_id"),
        summary,
        details=entity,
    )


def on_action_item(user_id, link, lane):  # lane: 'practice' | 'lesson'
    return create_task(
        user_id, text=link["action_item"], note=link["note_title"]
    ).id  # -> backlog_id


hooks = Hooks(
    on_event=on_event,
    on_action_item=on_action_item,
    llm_complete=lambda prompt: call_my_llm(prompt),
)  # llm_complete: only for llm_enrich
```

`on_someday(user_id, note_id, item)` keeps a "someday" seed (K§5) and only runs when
`Policy(someday=True)`; leave both off until the app has somewhere to show them.

**hygiene** (optional): issues only your app can see (duplicate entities). `detect` returns
`HygieneIssue`s or dicts of that shape; `merge` is optional, and without it `merge_entities`
answers 501 `not_supported`. A merge always runs as a dry run first; apply is audited via
`hooks.on_event`.

```python
from arp_notes.models import HygieneIssue


class HostHygiene:
    def detect(self, user_id, scope):  # scope: 'all' | 'note:<id>'
        return [
            HygieneIssue.model_validate(
                {
                    "key": "duplicate_entities:venue:3,9",
                    "kind": "duplicate_entities",
                    "severity": "action",
                    "title": "Two venues look the same",
                    "explanation": "'The Vanguard' and 'Village Vanguard' ...",
                    "subjects": [
                        {"entity_type": "venue", "entity_id": 3, "label": "The Vanguard"},
                        {"entity_type": "venue", "entity_id": 9, "label": "Village Vanguard"},
                    ],
                    "fixes": [],
                    "detected_by": "host",
                }
            )
        ]

    def merge(self, user_id, entity_type, keep_id, merge_ids, dry_run):
        return plan_or_apply_merge(user_id, entity_type, keep_id, merge_ids, dry_run)  # a MergePlan
```

The assembled object:

```python
from arp_notes.config import HostConfig


def build_host_config() -> HostConfig:
    return HostConfig(
        db=HostDb(DATABASE_URL),
        principal=HostPrincipal(),
        storage=storage,
        signer=HostSigner(),
        schemes=[VenueLinks()],
        policy=policy,
        judge=judge,
        hooks=hooks,
        hygiene=HostHygiene(),
    )
```

## 4 · Mount routes, register tools

```python
from arp_notes.fastapi import build_routers

cfg = build_host_config()
private, public = build_routers(cfg, "/api/v1")  # keep /api/v1: the CLI and UI call it
app.include_router(private, prefix="/api/v1")  # Bearer, through your Principal
app.include_router(public, prefix="/api/v1")  # signed attachment URLs, no Authorization
```

Behind a proxy pass `public_base_url="https://app.example.com"` as the third argument so signed
URLs name the public host. `mount_notes(app)` in the scaffold does exactly this.

**MCP tools.** `arp_notes.mcp.TOOLS` is the 13 notes tools plus 4 hygiene tools. Three ways:

```python
from arp_notes.mcp import TOOLS, register_fastmcp, rest_request

# (a) FastMCP (`fastmcp` or the `mcp` SDK) in the same process as the core:
register_fastmcp(mcp_server, cfg)  # handlers run in a worker thread
register_fastmcp(mcp_server, cfg, wrap=my_wrap)  # or pick how blocking calls are made

# (b) A FastMCP server whose tools call your REST API: generate the wrappers
for tool in TOOLS:
    ...  # req = rest_request(tool.name, args); api_call(req.method, req.path, params=req.params, json=req.json)

# (c) A hand-maintained registry (names, schemas, read/write lists in several files): iterate TOOLS
READ_TOOLS = [t.name for t in TOOLS if not t.writes]
WRITE_TOOLS = [t.name for t in TOOLS if t.writes]
# run one:  spec.handler(cfg, user_id, **args)    schema: spec.input_schema    text: spec.description
```

Never copy tool names by hand; when the core adds a tool, your parity test fails in one place. The
scaffold's `mount_notes_mcp_http` is a stand-in JSON-RPC endpoint so the kit's MCP checks run;
delete it once a real server serves the tools, and point the kit at it with `ARP_NOTES_MCP_URL`.

## 5 · Copy the DDL, then run the kit

Migrations are **copied, never applied by the package**. `init` copied
`arp_notes.schema.ddl()` (`001_notes.sql`) and each later delta (`002_note_links_lane.sql`, ...)
into your migrations folder, byte for byte. Apply them with your own runner, and keep this drift
test (the scaffold writes it) so a version bump cannot leave the copies stale:

```python
from arp_notes.schema import ddl, migrations


def test_migrations_match_arp_notes_core():
    shipped = {"001_notes.sql": ddl(), **dict(migrations())}
    for name, text in shipped.items():
        assert (MIGRATIONS / COPIES[name]).read_text(encoding="utf-8") == text
```

The kit is the feedback loop. A failure names the check, the request and the response:

```bash
uv run pytest tests/test_arp_notes_conformance.py            # in process, as the scaffold wrote it
uv run arp-notes-conformance --asgi myapp.main:app --token $TOKEN        # CLI, in process
uv run arp-notes-conformance --base-url https://staging.example.com --token $TOKEN   # over the wire
uv run arp-notes verify --conformance --app myapp            # after login; the post-release gate
uv run arp-notes-conformance --list                          # every check, grouped; --only sync
```

```python
from arp_notes_conformance import suite

suite(app=app, token="test-user-token")  # raises ConformanceFailure with the report
```

Checks the host's policy makes moot are skipped with a reason, never passed. The link checks need
an entity that exists in your app; give the kit a fixture of its own (a folder with `fixture.json`
and the notes it names; copy `packages/conformance/fixtures/` and edit it):

```json
{
  "source_system": "obsidian",
  "documents": {
    "masterclass": {"file": "vault/masterclass.md", "path": "Lessons/Masterclass.md", "title": "Masterclass", "kind": "masterclass"},
    "corpus":      {"file": "vault/corpus.md", "path": "Corpus/corpus.md", "title": "Corpus"},
    "scratch":     {"file": "vault/scratch.md", "path": "Scratch/Warm-ups.md", "title": "Warm-ups"}
  },
  "link_target": {"entity_type": "venue", "entity_id": 42, "child": {"entity_type": "show", "entity_id": 7}},
  "recognised_document": "masterclass"
}
```

`link_target` must exist for the test user and `child` is what your `children()` returns for it;
`recognised_document` is the note whose text your `reconcile` turns into a proposal. Pass it with
`suite(fixture="path/to/dir")`. Run the kit as a dedicated test user: it works in an
`arpn-conformance-<id>` workspace and deletes its notes, but blobs it uploaded stay until hygiene
sweeps them after 30 days.

## React

```jsx
import '@arpinator/notes-ui/tokens.css'   // the --arpn-* variables; map them to your tokens
import { createNotesApi, NotesList, NoteBody, ProposalReview } from '@arpinator/notes-ui'

const api = createNotesApi({ fetch: authedFetch })        // your fetch with the Bearer header; baseUrl '/api/v1'
const hrefForEntity = (type, id) => `/${type}s/${id}`      // components never fetch or route: you supply this

function NotesPage() {
  const [list, setList] = useState(null)
  useEffect(() => { api.listNotes({ limit: 50 }).then(setList) }, [])
  return list && <NotesList items={list.items} syncSources={list.sync_sources} hrefForNote={(id) => `/notes/${id}`} />
}

function NotePage({ id }) {
  const [note, setNote] = useState(null)
  const [caps, setCaps] = useState(null)
  useEffect(() => { api.getNote(id).then(setNote); api.getCapabilities().then(setCaps) }, [id])
  return note && caps && <NoteBody note={note} schemes={caps.schemes} hrefForEntity={hrefForEntity} onAttachmentExpired={() => api.getNote(id).then(setNote)} />
}
// Review: const proposal = await api.proposeEnrichment(id)
//   <ProposalReview proposal={proposal} noteTitle={note.title} onConfirm={(body) => api.confirmEnrichment(id, body)}
//                   onDecideLater={close} onRejectAll={(body) => api.confirmEnrichment(id, body)} />
// Editor: NoteEditor, NoteMetaFields, EditorRail, EditorToolbar, livePreview: see packages/ui/demo/scenes/editor.js
```

Style only through the `--arpn-*` variables (light on `:root`, dark under `[data-theme="dark"]` and
`prefers-color-scheme`); the package uses no Tailwind classes, so it fits Tailwind 3 and 4 apps.
`npm run demo --workspace packages/ui` serves every component on mock data.

## When it fails

| Symptom | Cause |
|---|---|
| `ValueError` naming a scheme | `reconcile` returned the wrong number of lists, or an `entity_id` that is not an int |
| every request 401 | `Principal` raised, or the kit's `--token` is not one it accepts |
| `relation "notes" does not exist` | the migrations were copied but not applied to this database |
| link checks skipped | the fixture names no `link_target` (above) |
| `mcp.*` checks skipped | no MCP endpoint answered; set `ARP_NOTES_MCP_URL` |
| `merge_entities` check skipped | no `Hygiene.merge`: the host answers 501 `not_supported`, which is allowed |
