"""Pydantic v2 models for every A.2 + K§2 + K§6 shape; schemas/*.json are generated from them.

C0 stub (ga-mxal.5): the names exist so signatures elsewhere import and type-check. C1a
(ga-mxal.25) owns the fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    # Clients and servers tolerate unknown fields (K§2).
    model_config = ConfigDict(extra="allow")


class Attachment(_Model): ...


class NoteLink(_Model): ...


class Note(_Model): ...


class NoteSummary(_Model): ...


class ManifestRow(_Model): ...


class ManifestPage(_Model): ...  # {items: [ManifestRow], next_after?}


class NoteUpsert(_Model): ...


class UpsertResult(_Model): ...


class TombstoneResult(_Model): ...  # {tombstoned: int, unknown: [str]}


class ProposedLink(_Model): ...


class ProposedAction(_Model): ...


class Proposal(_Model): ...


class ConfirmBody(_Model): ...


class ConfirmResult(_Model): ...


class Capabilities(_Model): ...


class HygieneIssue(_Model): ...


class HygieneBlock(_Model): ...


class MergePlan(_Model): ...
