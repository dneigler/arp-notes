"""`arp-notes init --host fastapi`: scaffold an arp-notes integration into an existing app.

Owner: C9 ga-mxal.23 (ADR §9.8). It writes three things and edits nothing that exists:

- the adapter file: port stubs with `TODO(arp-notes)` markers, plus `mount_notes(app)` and the MCP
  registration (`templates/fastapi/arp_notes_host.py.tmpl`);
- the migration copies: `arp_notes.schema.ddl()` and every later SQL file of the installed
  arp-notes-core, verbatim, because a host copies migrations and never applies the package's;
- a test file with the drift test and the conformance run, the integrator's definition of done.

An existing file is never overwritten without `--force`. `--only migrations` is the upgrade path
after bumping the arp-notes-core pin: it copies the new SQL and leaves the adapter alone.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path

from arp_notes_cli.registry import Subparsers

HOSTS = ("fastapi",)
PARTS = ("adapter", "migrations", "tests")
ADAPTER_FILE = "arp_notes_host.py"
TESTS_FILE = "test_arp_notes_conformance.py"
TODO_MARK = "TODO(arp-notes)"

MIGRATION_DIRS = (
    "migrations",
    "db/migrations",
    "database/migrations",
    "backend/migrations",
    "sql/migrations",
)
TEST_DIRS = ("tests", "backend/tests", "test")
PACKAGE_DIRS = ("app", "backend/app", "src/app")
# Directories that hold the import root rather than a package: `backend/app` is imported as `app`.
IMPORT_ROOTS = ("src", "backend")

NOT_INSTALLED = (
    "arp-notes init reads the SQL from arp-notes-core, which is not installed in this "
    "environment.\n"
    "Install it where the host app lives, then run init from that environment:\n"
    '  uv add "arp-notes-core @ git+https://github.com/dneigler/arp-notes@<tag>'
    '#subdirectory=packages/core"\n'
    "  uv run arp-notes init --host fastapi"
)


class InitError(Exception):
    """Bad input or an unusable project; the message says what to change. Exit code 2."""


@dataclass
class Target:
    """One file init would write: where, what, and what is there now."""

    part: str
    path: Path
    content: str
    state: str = "new"  # 'new' | 'unchanged' | 'differs'

    def inspect(self) -> Target:
        if self.path.exists():
            current = self.path.read_text(encoding="utf-8") if self.path.is_file() else None
            self.state = "unchanged" if current == self.content else "differs"
        return self


# -- the installed core -----------------------------------------------------------------------


def core_sql() -> list[tuple[str, str]]:
    """(file name, text) of every SQL file arp-notes-core ships, 001 first."""
    try:
        from arp_notes.schema import ddl, migrations
    except ImportError as exc:
        raise InitError(NOT_INSTALLED) from exc
    return [("001_notes.sql", ddl()), *migrations()]


def core_version() -> str:
    try:
        return metadata.version("arp-notes-core")
    except metadata.PackageNotFoundError:
        return "unknown version"


def ui_install_line(version: str) -> str:
    """The K§12.6 install line for @arpinator/notes-ui: the tarball attached to the release.

    `0.1.0rc1` (PEP 440) is tag `v0.1.0-rc.1` and npm version `0.1.0-rc.1`; `0.1.0` is `v0.1.0`.
    A version that is not one of those leaves `<tag>` and `<version>` for the reader to fill in.
    """
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:rc(\d+))?", version)
    npm = "<version>"
    if match:
        npm = match[1] + (f"-rc.{match[2]}" if match[2] else "")
    tag = f"v{npm}" if match else "<tag>"
    return (
        "npm install https://github.com/dneigler/arp-notes/releases/download/"
        f"{tag}/arpinator-notes-ui-{npm}.tgz"
    )


# -- choosing where things go -----------------------------------------------------------------


def first_dir(root: Path, candidates: tuple[str, ...], default: str) -> str:
    return next((c for c in candidates if (root / c).is_dir()), default)


def detect_package(root: Path) -> str:
    """The folder the adapter goes in: `app/`, `backend/app/`, `src/app/`, the one package under
    `src/`, else `app/` (created)."""
    found = first_dir(root, PACKAGE_DIRS, "")
    if found:
        return found
    src = root / "src"
    if src.is_dir():
        packages = sorted(p.name for p in src.iterdir() if (p / "__init__.py").is_file())
        if len(packages) == 1:
            return f"src/{packages[0]}"
    return "app"


def module_name(package: str) -> str:
    """The dotted import path of `package`: `app` -> `app`, `src/shop` -> `shop`, `backend/app` ->
    `app`. Pass --module when the app is imported another way."""
    parts = [p for p in Path(package).parts if p not in (".", "")]
    if len(parts) > 1 and parts[0] in IMPORT_ROOTS:
        parts = parts[1:]
    return ".".join(parts)


def migration_names(files: list[tuple[str, str]], number: int | None) -> dict[str, str]:
    """core SQL file name -> the name of its copy in the host.

    Default: `arp_notes_001_notes.sql`. With --migration-number N the host's own numbering is used
    instead, one number per file in order: `043_notes.sql`, `044_note_links_lane.sql`.
    """
    if number is None:
        return {name: f"arp_notes_{name}" for name, _ in files}
    return {
        name: f"{number + i:03d}_{re.sub(r'^\d+_', '', name)}" for i, (name, _) in enumerate(files)
    }


def relpath(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target, start)).as_posix()


# -- rendering --------------------------------------------------------------------------------


def template(name: str) -> str:
    return (resources.files("arp_notes_cli") / "templates" / "fastapi" / name).read_text(
        encoding="utf-8"
    )


def render(text: str, **values: str) -> str:
    for key, value in values.items():
        text = text.replace(f"@@{key}@@", value)
    left = re.findall(r"@@[A-Z_]+@@", text)
    if left:  # a template bug, not a user error
        raise RuntimeError(f"unfilled template field {left[0]}")
    return text


def plan(args: argparse.Namespace) -> list[Target]:
    root = Path(args.dir).resolve()
    if not root.is_dir():
        raise InitError(f"--dir {args.dir}: not a directory")
    wanted = set(args.only or PARTS)
    package = (args.package or detect_package(root)).strip("/")
    migrations_dir = (args.migrations_dir or first_dir(root, MIGRATION_DIRS, "migrations")).strip(
        "/"
    )
    tests_dir = (args.tests_dir or first_dir(root, TEST_DIRS, "tests")).strip("/")
    module = args.module or module_name(package)
    sql = core_sql()
    names = migration_names(sql, args.migration_number)

    targets: list[Target] = []
    if "adapter" in wanted:
        text = render(
            template("arp_notes_host.py.tmpl"),
            CORE_VERSION=core_version(),
            MODULE=module,
            TESTS_PATH=f"{tests_dir}/{TESTS_FILE}",
        )
        targets.append(Target("adapter", root / package / ADAPTER_FILE, text))
    if "migrations" in wanted:
        for core_name, text in sql:
            targets.append(Target("migrations", root / migrations_dir / names[core_name], text))
    if "tests" in wanted:
        copies = "\n".join(f'    "{core}": "{host}",' for core, host in names.items())
        text = render(
            template("test_arp_notes_conformance.py.tmpl"),
            MODULE=module,
            MIGRATIONS_FROM_TESTS=relpath(root / migrations_dir, root / tests_dir),
            COPIES=copies,
        )
        targets.append(Target("tests", root / tests_dir / TESTS_FILE, text))
    return [t.inspect() for t in targets]


# -- writing ----------------------------------------------------------------------------------


def ensure_package(folder: Path, root: Path) -> None:
    """A package folder init creates gets an `__init__.py`; one that exists is left as it is."""
    if folder.exists() or folder == root:
        return
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("", encoding="utf-8")


def write(target: Path, content: str, root: Path, part: str) -> None:
    if part == "adapter":
        ensure_package(target.parent, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def verb(target: Target, force: bool, dry_run: bool) -> str:
    if target.state == "unchanged":
        return "unchanged"
    if target.state == "differs" and not force:
        return "exists (differs)"
    if dry_run:
        return "would overwrite" if target.state == "differs" else "would create"
    return "overwrote" if target.state == "differs" else "created"


def next_steps(args: argparse.Namespace, targets: list[Target], root: Path) -> list[str]:
    steps: list[str] = []
    by_part = {t.part: t for t in targets}
    adapter = by_part.get("adapter")
    if adapter is not None and adapter.path.is_file():
        todos = adapter.path.read_text(encoding="utf-8").count(TODO_MARK)
        module = args.module or module_name(relpath(adapter.path.parent, root))
        steps += [
            f"Fill in the {todos} {TODO_MARK} markers in {relpath(adapter.path, root)}: "
            "HostDb, HostPrincipal, HostLinks.",
            "Mount the routes where you create your FastAPI app:\n"
            f"       from {module}.arp_notes_host import mount_notes\n"
            "       mount_notes(app)\n"
            "   and call register_notes_mcp(your_fastmcp_server) where you build your MCP server.",
        ]
    migrations = [t for t in targets if t.part == "migrations"]
    if migrations:
        folder = relpath(migrations[0].path.parent, root)
        steps.append(f"Apply the SQL in {folder}/ with your usual migration runner.")
    tests = by_part.get("tests")
    if tests is not None:
        steps.append(
            f"Make {relpath(tests.path, root)} pass: set its TOKEN, then run it. Adoption is "
            "done when the conformance kit is green."
        )
    if not steps:
        return []
    numbered = [f"  {i}. {step}" for i, step in enumerate(steps, 1)]
    return [
        "",
        "Next:",
        *numbered,
        "",
        "React UI (optional): " + ui_install_line(core_version()),
        "Recipe: INTEGRATING.md in https://github.com/dneigler/arp-notes",
    ]


def run_init(args: argparse.Namespace) -> int:
    if args.host not in HOSTS:
        raise InitError(f"--host {args.host}: supported hosts are {', '.join(HOSTS)}")
    root = Path(args.dir).resolve()
    targets = plan(args)
    blocked = False
    print(f"arp-notes init --host {args.host} (arp-notes-core {core_version()})")
    for target in targets:
        what = verb(target, args.force, args.dry_run)
        print(f"  {what:17} {relpath(target.path, root)}")
        if target.state == "unchanged" or args.dry_run:
            continue
        if target.state == "differs" and not args.force:
            blocked = True
            continue
        write(target.path, target.content, root, target.part)
    if blocked:
        print(
            "\nFiles marked 'exists (differs)' were left alone. Compare them with the template or "
            "the installed arp-notes-core, then pass --force to replace them.",
            file=sys.stderr,
        )
    if not args.dry_run:
        for line in next_steps(args, targets, root):
            print(line)
    return 1 if blocked else 0


def _cmd_init(args: argparse.Namespace) -> int:
    try:
        return run_init(args)
    except InitError as exc:
        print(f"arp-notes init: {exc}", file=sys.stderr)
        return 2


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "init",
        help="Scaffold an arp-notes integration into a host app.",
        description=(
            "Write the adapter file (port stubs with TODO(arp-notes) markers, the router mount "
            "and the MCP registration), copy arp-notes-core's SQL into your migrations folder "
            "and add a test file with the drift test and the conformance kit. Nothing that "
            "exists is overwritten without --force. Run it in an environment that has "
            "arp-notes-core installed, from the app's root. Exit codes: 0 ok, 1 a file differs "
            "and was left alone, 2 bad input."
        ),
    )
    parser.add_argument("--host", required=True, choices=HOSTS, help="the host framework")
    parser.add_argument("--dir", default=".", help="the app's root (default: the current folder)")
    parser.add_argument(
        "--package", help="folder for the adapter file (default: detected, else app)"
    )
    parser.add_argument("--module", help="dotted import path of --package (default: derived)")
    parser.add_argument(
        "--migrations-dir", help="where SQL copies go (default: detected, else migrations)"
    )
    parser.add_argument(
        "--tests-dir", help="where the test file goes (default: detected, else tests)"
    )
    parser.add_argument(
        "--migration-number",
        type=int,
        metavar="N",
        help="name the SQL copies with the app's own numbers from N (043_notes.sql, 044_...)",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=PARTS,
        help="write only this part (repeatable); 'migrations' is the upgrade after a version bump",
    )
    parser.add_argument("--force", action="store_true", help="overwrite files that differ")
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would be written, write nothing"
    )
    parser.set_defaults(func=_cmd_init)
