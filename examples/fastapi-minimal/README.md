# fastapi-minimal

The smallest arp-notes host: [`app.py`](app.py) is one file with every port an integrator writes.
It is also the conformance kit's CI target, so it cannot rot: `test_app.py` runs the whole kit
against it in process and over HTTP, and checks that [`migrations/`](migrations) still equal what
`arp-notes-core` ships.

| In `app.py` | Port | Swap it for |
|---|---|---|
| `PsycopgDb` | `Db` | the connection, pool or session your app already has |
| `BearerPrincipal` | `Principal` | your auth (JWT, session cookie) |
| `DiskStorage` | `Storage` | `PostgresStorage` or `S3Storage` |
| `FixedSigner` | `Signer` | your session secret |
| `ToyScheme` | `LinkSchemes` | your entities: venues, pieces, invoices |
| `Policy()`, `Hooks(...)` | `Policy`, `Hooks` | your limits and activity log |
| `mount_mcp` | MCP tools | `register_fastmcp(server, cfg)` or your own registry |

`migrations/` is what `arp-notes init --host fastapi --only migrations` writes. The host applies
them itself (`python app.py migrate`); the package never does.

```bash
createdb notes_example
export DATABASE_URL=postgresql:///notes_example EXAMPLE_TOKEN=dev-token
uv run python examples/fastapi-minimal/app.py migrate
cd examples/fastapi-minimal && uv run uvicorn app:create_app --factory --port 8000
# in another shell
uv run arp-notes-conformance --base-url http://127.0.0.1:8000 --token dev-token
uv run pytest examples/fastapi-minimal     # the same, in CI form (starts its own Postgres)
```

Its one link scheme knows three toy entities, which is why the kit's link checks run against it
with the bundled fixture. A real host writes a fixture of its own (INTEGRATING.md).
