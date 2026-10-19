"""notes/links/blobs/tickets CRUD over the Db port. Owner: C1b (ga-mxal.8).

C0 stubs only the function the contract names (K§7); C1b adds the rest of the CRUD.
"""

from __future__ import annotations

from arp_notes.config import HostConfig
from arp_notes.models import ConfirmBody, ConfirmResult


def confirm_links(cfg: HostConfig, user_id: str, note_id: int, body: ConfirmBody) -> ConfirmResult:
    raise NotImplementedError("C1b: repo.confirm_links")
