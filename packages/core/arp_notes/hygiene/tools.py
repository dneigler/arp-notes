"""Hygiene MCP tool specs: dismiss_issue, resolve_tombstone (H1a), apply_fix, merge_entities (H1b).

arp_notes.mcp.TOOLS imports TOOLS from here.

The specs are built on first access to `TOOLS` (module `__getattr__`), not at import: `mcp`
imports this module at its top and needs `ToolSpec` and its helpers, which `mcp` defines further
down, so building them here at import time would be a circular import in one order or the other.
H1b adds its specs by appending to the list `_build` returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from arp_notes import hygiene
from arp_notes.config import HostConfig

if TYPE_CHECKING:
    from arp_notes.mcp import ToolSpec

    TOOLS: list[ToolSpec]

_built: list[ToolSpec] | None = None


def _build() -> list[ToolSpec]:
    from arp_notes.mcp import _Args, _handler, _json, _spec  # defined before mcp reads TOOLS

    class DismissIssue(_Args):
        issue_key: str = Field(
            description="The `key` of the hygiene issue to hide, copied exactly as it appears."
        )
        reason: str | None = Field(
            None, description="Why the user wants it hidden, in a few words."
        )

    class ResolveTombstone(_Args):
        note_id: int = Field(description="The id of the note whose source was deleted.")
        action: Literal["keep", "delete"] = Field(
            description="'keep' hides the note and stops the reminder; its links stay. "
            "'delete' removes the note and its links for good and cannot be undone."
        )

    @_handler(DismissIssue)
    def dismiss_issue(cfg: HostConfig, user_id: str, args: DismissIssue) -> dict[str, Any]:
        return _json(hygiene.dismiss(cfg, user_id, args.issue_key, args.reason))

    @_handler(ResolveTombstone)
    def resolve_tombstone(cfg: HostConfig, user_id: str, args: ResolveTombstone) -> dict[str, Any]:
        return _json(hygiene.resolve_tombstone(cfg, user_id, args.note_id, args.action))

    return [
        _spec(
            "dismiss_issue",
            dismiss_issue,
            DismissIssue,
            "Hide one hygiene issue so it stops appearing. Nothing else changes, and the issue "
            "comes back if the things it is about change. First explain the issue to the user in "
            "plain language and ask whether they want it hidden; do not dismiss on your own.",
            writes=True,
        ),
        _spec(
            "resolve_tombstone",
            resolve_tombstone,
            ResolveTombstone,
            "Settle a note whose source was deleted (a `tombstoned_note` hygiene issue). 'keep' "
            "leaves the hidden copy and stops the reminder; 'delete' removes the note and its "
            "links for good, with no undo. First explain the situation to the user in plain "
            "language, say which choice does what, and ask them to choose; never pick 'delete' "
            "without an explicit yes. Only works on a note that was deleted at its source.",
            writes=True,
        ),
    ]


def __getattr__(name: str) -> Any:
    global _built
    if name == "TOOLS":
        if _built is None:
            built = _build()
            # _build imports mcp, which may read TOOLS (and so build) before it returns here.
            # The first list built is the one mcp.TOOLS holds, so it wins.
            if _built is None:
                _built = built
        return _built
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
