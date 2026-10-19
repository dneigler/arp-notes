"""Write schemas/*.json from the Pydantic models (K§7: schemas are generated, never hand-edited).

    python -m arp_notes.schemas.generate           # rewrite the files
    python -m arp_notes.schemas.generate --check   # exit 1 when the checked-in files differ

One file per model, named by snake-casing the class (`HygieneIssue` -> `hygiene_issue.json`; the
K§6.1 hygiene shapes therefore match `hygiene_*.json`). Each file is a self-contained JSON Schema
2020-12 document: its dependencies sit under `$defs`, so a consumer (the UI's ajv, the
conformance kit) can load one file on its own.
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from arp_notes import models

DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMAS_DIR = Path(__file__).resolve().parent


def shape_models() -> dict[str, type[BaseModel]]:
    """Every public wire model, by class name, in definition order."""
    return {
        name: obj
        for name, obj in vars(models).items()
        if inspect.isclass(obj)
        and issubclass(obj, BaseModel)
        and obj.__module__ == models.__name__
        and not name.startswith("_")
    }


def file_stem(shape: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", shape).lower()


def render(model: type[BaseModel]) -> str:
    schema: dict[str, Any] = {"$schema": DIALECT, **model.model_json_schema()}
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_all() -> dict[str, str]:
    """{file name: file text} for every schema."""
    return {f"{file_stem(name)}.json": render(model) for name, model in shape_models().items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail on drift instead of writing")
    args = parser.parse_args(argv)
    rendered = render_all()
    stale = [
        name
        for name, text in rendered.items()
        if not (SCHEMAS_DIR / name).exists() or (SCHEMAS_DIR / name).read_text("utf-8") != text
    ]
    extra = sorted(p.name for p in SCHEMAS_DIR.glob("*.json") if p.name not in rendered)
    if args.check:
        for name in stale:
            print(f"out of date: {name}", file=sys.stderr)
        for name in extra:
            print(f"no model for: {name}", file=sys.stderr)
        return 1 if stale or extra else 0
    for name in stale:
        (SCHEMAS_DIR / name).write_text(rendered[name], encoding="utf-8")
    for name in extra:
        (SCHEMAS_DIR / name).unlink()
    print(f"{len(rendered)} schemas ({len(stale)} written, {len(extra)} removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
