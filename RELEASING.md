# Releasing

Packages are semver and tagged together. There is no registry publishing in v0.1 (PyPI and npm
come later); hosts install by tag.

## Tags

| Tag | Meaning |
|---|---|
| `v0.1.0-rc.1` | RC1: core, CLI and conformance importable and passing, for the first host integration. |
| `v0.1.0-rc.2` | RC2: the UI package is ready for hosts to pin. |
| `v0.1.0` | Release: everything, `protocol_version: 1`, install lines verified from a clean environment. |

Only the release lanes tag. Feature lanes push to `main` and never tag. Nothing deploys from this
repository.

## Cutting a tag

1. Wait for green CI on the final `main` tip. Never tag a cancelled or in-progress run.
2. Set the versions in one commit. Python uses PEP 440 and npm uses semver, so `v0.1.0-rc.1` is
   `0.1.0rc1` in `packages/{core,cli,conformance}/pyproject.toml` and `__version__`, and
   `0.1.0-rc.1` in `packages/ui/package.json`. A final release is `0.1.0` in both.
3. `uv run pytest`, `npm test` and `npm run test:e2e` pass locally.
4. `git tag v0.1.0-rc.1 && git push origin v0.1.0-rc.1`.
5. Confirm the install lines below from a clean directory, using the new tag.

## Install-by-tag lines

Python (replace `v0.1.0` with the tag):

```bash
uv add "arp-notes-core @ git+https://github.com/dneigler/arp-notes@v0.1.0#subdirectory=packages/core"
uv add "arp-notes-conformance @ git+https://github.com/dneigler/arp-notes@v0.1.0#subdirectory=packages/conformance"
uvx --from "arp-notes @ git+https://github.com/dneigler/arp-notes@v0.1.0#subdirectory=packages/cli" arp-notes --help
```

UI package. Plain npm cannot install a subdirectory of a git repository, so the release lane
attaches the packed tarball (`npm pack --workspace packages/ui`) to the GitHub release and hosts
install that. The release lane verifies both installers in clean directories before announcing the
tag:

```bash
npm install https://github.com/dneigler/arp-notes/releases/download/v0.1.0/arpinator-notes-ui-0.1.0.tgz
bun add https://github.com/dneigler/arp-notes/releases/download/v0.1.0/arpinator-notes-ui-0.1.0.tgz
```

Release assets are immutable: hosts' lockfiles pin the tarball's integrity, so never replace an
asset under an existing tag. A bad tarball means the next `rc.N`.

Import the tokens once: `import '@arpinator/notes-ui/tokens.css'`.

For local development, use a `uv` path override (`[tool.uv.sources]`) or `npm link`.

## Migrations are copied, not imported

A host copies `arp_notes.schema.ddl()` at its pinned version into its own migrations and keeps a
drift test. A later core version that adds columns ships a new numbered SQL file; hosts copy it.
