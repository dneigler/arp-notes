"""MCP tool specs (A.3 + K§6.3) and FastMCP registration. Owner: C4 (ga-mxal.11).

TOOLS = [*NOTES_TOOLS, *hygiene.tools.TOOLS]. C4 fills NOTES_TOOLS (13 specs); H1a/H1b fill the
hygiene specs (4), for 17 in total.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from arp_notes.config import HostConfig
from arp_notes.hygiene import tools as hygiene_tools


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]  # handler(config, user_id, **args)
    writes: bool = False  # the R/W column of A.3


NOTES_TOOLS: list[ToolSpec] = []

TOOLS: list[ToolSpec] = [*NOTES_TOOLS, *hygiene_tools.TOOLS]


def register_fastmcp(app: Any, cfg: HostConfig, wrap: Callable[..., Any] | None = None) -> None:
    raise NotImplementedError("C4: mcp.register_fastmcp")
