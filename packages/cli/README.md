# arp-notes (CLI)

```
uvx arp-notes --help
```

Subcommands: `config`, `capabilities`, `scan`, `status`, `sync`, `verify`, `tombstone`, `pull`,
`init`, `conformance`. All are stubs until their lane lands; a stub prints `not implemented` and
exits 2. Usage documentation arrives with each lane (CLI-a ga-mxal.6 owns the usage section).

## Adding a subcommand

`arp_notes_cli.main` discovers every module in the package. A module contributes subcommands by
defining `register(subparsers)`; the handler it sets with `parser.set_defaults(func=...)` takes the
parsed `argparse.Namespace` and returns the process exit code. See `arp_notes_cli/registry.py`.
