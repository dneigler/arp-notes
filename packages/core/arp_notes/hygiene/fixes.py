"""apply_fix and merge_entities: dry run first, confirm_token, audited (K§6.3).

Owner: H1b (ga-mxal.31).

Both writes follow one protocol. A call without a `confirm_token` is always a dry run: it returns
the plan and a token. Applying means sending that token back. The token is
HMAC(signer secret, expiry + user_id + canonical plan JSON), good for 10 minutes and for one use.
Applying re-plans against the current state first and refuses with 409 `plan_changed` when the
plan is not the one the token was issued for, so a client LLM can only apply what the user saw.

Single use is enforced in memory (`_used`) and by the re-plan: once an apply has changed the state,
the same token no longer matches. K§1 adds no table for tokens, so a host that runs several
processes relies on the second check alone.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from arp_notes.config import HostConfig
from arp_notes.hygiene import detect
from arp_notes.models import (
    ApplyFixApplied,
    ApplyFixBody,
    ApplyFixDryRun,
    MergeEntitiesApplied,
    MergeEntitiesBody,
    MergeEntitiesDryRun,
    MergePlan,
)
from arp_notes.ports import HygieneMerge
from arp_notes.repo import NotesError

log = logging.getLogger(__name__)

TOKEN_TTL_S = 10 * 60  # K§6.3
FIX_EVENT = "note_hygiene_fix"  # A.1 activity_log.event_type constants
MERGE_EVENT = "note_merge_applied"

router = APIRouter()  # config-free part; the routes need a config, see build_router


class PlanChanged(NotesError):
    """The plan differs from the one the confirm_token was issued for (K§6.3)."""

    status = 409
    code = "plan_changed"


class NotSupported(NotesError):
    """The host did not supply what this write needs (cfg.hygiene.merge)."""

    status = 501
    code = "not_supported"


class AuditUnavailable(NotesError):
    """An irreversible write needs Hooks.on_event to audit it, and the host set none."""

    status = 501
    code = "audit_unavailable"


class InvalidConfirmToken(NotesError):
    status = 422
    code = "invalid_confirm_token"


class TokenExpired(NotesError):
    status = 410
    code = "token_expired"


class TokenUsed(NotesError):
    status = 409
    code = "token_used"


class IssueNotFound(NotesError):
    status = 404
    code = "issue_not_found"


class InvalidFixIndex(NotesError):
    status = 422
    code = "invalid_fix_index"


class FixNotApplicable(NotesError):
    """apply_fix only runs fixes whose tool is `apply_fix`; others are separate tool calls."""

    status = 422
    code = "fix_not_applicable"


class InvalidMerge(NotesError):
    status = 422
    code = "invalid_merge"


# ---------------------------------------------------------------------------------------------
# confirm_token
# ---------------------------------------------------------------------------------------------

_used: dict[str, int] = {}  # token -> its expiry, so entries can be dropped once they lapse
_used_lock = threading.Lock()


def _now() -> int:
    return int(time.time())


def _canonical(plan: Any) -> str:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _mac(cfg: HostConfig, user_id: str, expires: int, plan: Any) -> str:
    secret = cfg.signer.secret
    key = secret.encode() if isinstance(secret, str) else secret
    message = f"{expires}\n{user_id}\n{_canonical(plan)}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def issue_token(cfg: HostConfig, user_id: str, plan: Any) -> tuple[str, str]:
    """-> (confirm_token, expires_at as ISO-8601 UTC)."""
    expires = _now() + TOKEN_TTL_S
    token = f"{expires}.{_mac(cfg, user_id, expires, plan)}"
    return token, datetime.fromtimestamp(expires, UTC).strftime("%Y-%m-%dT%H:%M:%S")


def consume_token(cfg: HostConfig, user_id: str, token: str, plan: Any) -> None:
    """Accept `token` for `plan` once. Raises InvalidConfirmToken, TokenExpired, TokenUsed,
    PlanChanged."""
    stamp, _, mac = token.partition(".")
    if not (stamp.isascii() and stamp.isdigit() and mac):
        raise InvalidConfirmToken("confirm_token is not one this server issued; run a dry run")
    expires = int(stamp)
    now = _now()
    if expires < now:
        raise TokenExpired("the confirm_token expired; run the dry run again")
    with _used_lock:
        for old, old_expires in list(_used.items()):
            if old_expires < now:
                del _used[old]
        if token in _used:
            raise TokenUsed("that confirm_token was already used; run the dry run again")
        if not hmac.compare_digest(mac, _mac(cfg, user_id, expires, plan)):
            raise PlanChanged("the plan changed since the dry run; run the dry run again")
        _used[token] = expires


# ---------------------------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------------------------


def _audit(
    cfg: HostConfig, user_id: str, event_type: str, entity: dict[str, Any], summary: str
) -> int:
    """Call Hooks.on_event after a write. -> the host's event id when it returns an int, else 0.

    Never raises: the write has happened, and reporting it as failed would invite a retry.
    """
    hooks = cfg.hooks
    if hooks is None or hooks.on_event is None:
        return 0
    try:
        result: Any = hooks.on_event(user_id, event_type, entity, summary)
    except Exception:
        log.exception("Hooks.on_event(%s) failed after the write was applied", event_type)
        return 0
    return result if isinstance(result, int) and not isinstance(result, bool) else 0


# ---------------------------------------------------------------------------------------------
# apply_fix
# ---------------------------------------------------------------------------------------------

_BLOB_COLUMNS = "id, sha256, mime, size_bytes, storage_path, created_at"


def _find_issue(cfg: HostConfig, user_id: str, issue_key: str) -> Any:
    for issue in detect.collect(cfg, user_id, "all"):
        if issue.key == issue_key:
            return issue
    return None


def _blob_plan(cfg: HostConfig, user_id: str, issue_key: str) -> dict[str, Any]:
    rows = cfg.db.run(
        f"SELECT {_BLOB_COLUMNS} FROM blobs b WHERE b.user_id = %s"
        f" AND b.created_at < CURRENT_TIMESTAMP - INTERVAL '{detect.UNREFERENCED_BLOB_DAYS} days'"
        " AND NOT EXISTS (SELECT 1 FROM note_attachments a WHERE a.blob_id = b.id)"
        " ORDER BY b.id",
        [user_id],
    )
    return {
        "action": "delete_unreferenced_blobs",
        "issue_key": issue_key,
        "blob_ids": [row["id"] for row in rows],
        "count": len(rows),
        "freed_bytes": sum(row["size_bytes"] or 0 for row in rows),
        "reversible": False,
    }


def _delete_blobs(cfg: HostConfig, user_id: str, blob_ids: list[int]) -> list[dict[str, Any]]:
    """Delete exactly `blob_ids`, all or none. -> the deleted rows, as audit snapshots."""
    with cfg.db.transaction():
        rows = cfg.db.run(
            f"DELETE FROM blobs b WHERE b.user_id = %s AND b.id = ANY(%s)"
            " AND NOT EXISTS (SELECT 1 FROM note_attachments a WHERE a.blob_id = b.id)"
            f" RETURNING {_BLOB_COLUMNS}",
            [user_id, blob_ids],
        )
        if len(rows) != len(blob_ids):  # a note started using one in the meantime
            raise PlanChanged("a stored file is in use now; run the dry run again")
    return sorted(rows, key=lambda row: row["id"])


def apply_fix(
    cfg: HostConfig, user_id: str, issue_key: str, fix_index: int, confirm_token: str | None = None
) -> dict[str, Any]:
    """Dry run when `confirm_token` is None, else apply (K§6.3).

    Runs the fixes whose tool is `apply_fix`, which core defines for `unreferenced_blobs` only.
    Raises IssueNotFound, InvalidFixIndex, FixNotApplicable, NotSupported, plus the token errors.
    """
    issue = _find_issue(cfg, user_id, issue_key)
    if issue is None:
        if confirm_token is not None:
            raise PlanChanged("the issue is gone; run the dry run again")
        raise IssueNotFound(f"no open hygiene issue {issue_key[:80]!r}; copy `key` from a block")
    if not 0 <= fix_index < len(issue.fixes):
        raise InvalidFixIndex(f"fix_index must be 0..{len(issue.fixes) - 1} for this issue")
    fix = issue.fixes[fix_index]
    if fix.tool != "apply_fix":
        raise FixNotApplicable(
            f"fix {fix_index} is not run by apply_fix; call {fix.tool} with {fix.arguments}",
            tool=fix.tool,
            arguments=fix.arguments,
        )
    if issue.kind != "unreferenced_blobs" or issue.detected_by != "core":
        raise NotSupported(f"apply_fix cannot run fixes for {issue.kind} issues")

    plan = _blob_plan(cfg, user_id, issue_key)
    plan["fix_index"] = fix_index
    if confirm_token is None:
        token, expires_at = issue_token(cfg, user_id, plan)
        return ApplyFixDryRun(
            dry_run=True, plan=plan, confirm_token=token, expires_at=expires_at
        ).model_dump(mode="json")

    consume_token(cfg, user_id, confirm_token, plan)
    snapshots = _delete_blobs(cfg, user_id, plan["blob_ids"])
    storage_errors = 0
    for row in snapshots:  # after the commit: stray bytes are harmless, a dangling row is not
        try:
            cfg.storage.delete(user_id, row["sha256"])
        except Exception:
            storage_errors += 1
            log.exception("Storage.delete failed for blob %s", row["id"])
    entity = {
        "entity_type": "blob",
        "entity_id": snapshots[0]["id"] if snapshots else 0,
        "event": FIX_EVENT,
        "issue_key": issue_key,
        "plan": plan,
        "snapshots": snapshots,
    }
    noun = "file" if len(snapshots) == 1 else "files"
    event_id = _audit(
        cfg, user_id, FIX_EVENT, entity, f"Deleted {len(snapshots)} unused stored {noun}"
    )
    result: dict[str, Any] = {
        "deleted_blobs": len(snapshots),
        "freed_bytes": plan["freed_bytes"],
        "audit_event_id": event_id,
    }
    if storage_errors:
        result["storage_errors"] = storage_errors
    return {"applied": True, "result": result}


# ---------------------------------------------------------------------------------------------
# merge_entities
# ---------------------------------------------------------------------------------------------


def _host_merge(
    cfg: HostConfig,
    user_id: str,
    entity_type: str,
    keep_id: int,
    merge_ids: list[int],
    dry_run: bool,
) -> MergePlan:
    host = cfg.hygiene
    if host is None or not isinstance(host, HygieneMerge):
        raise NotSupported("this app does not support merging entities")
    try:
        plan = host.merge(user_id, entity_type, keep_id, merge_ids, dry_run)
    except (ValueError, LookupError) as exc:  # the host's "no such entity" and the like
        raise InvalidMerge(str(exc) or "the host refused this merge") from exc
    return plan if isinstance(plan, MergePlan) else MergePlan.model_validate(plan)


def merge_entities(
    cfg: HostConfig,
    user_id: str,
    entity_type: str,
    keep_id: int,
    merge_ids: list[int],
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> MergeEntitiesDryRun | MergeEntitiesApplied:
    """Merge duplicate host entities into `keep_id` through `cfg.hygiene.merge` (K§6.3).

    Applies only with dry_run=False AND a confirm_token from a dry run of the same merge;
    anything else is a dry run. Raises NotSupported (no host merge), InvalidMerge,
    AuditUnavailable, plus the token errors.
    """
    ids = sorted(set(merge_ids))
    if not entity_type or not ids or keep_id in ids:
        raise InvalidMerge("merge_ids must be non-empty and must not contain keep_id")
    apply = not dry_run and confirm_token is not None
    if apply and (cfg.hooks is None or cfg.hooks.on_event is None):
        raise AuditUnavailable("merges are irreversible and this app has no audit log to record it")

    plan = _host_merge(cfg, user_id, entity_type, keep_id, ids, True)
    plan_json = plan.model_dump(mode="json")
    if not apply or confirm_token is None:
        token, expires_at = issue_token(cfg, user_id, plan_json)
        return MergeEntitiesDryRun(plan=plan, confirm_token=token, expires_at=expires_at)

    consume_token(cfg, user_id, confirm_token, plan_json)
    applied = _host_merge(cfg, user_id, entity_type, keep_id, ids, False)
    entity = {
        "entity_type": entity_type,
        "entity_id": keep_id,
        "event": MERGE_EVENT,
        "plan": applied.model_dump(mode="json"),  # extras carry the host's pre-merge snapshots
    }
    merged = ", ".join(str(i) for i in ids)
    event_id = _audit(
        cfg, user_id, MERGE_EVENT, entity, f"Merged {entity_type} {merged} into {keep_id}"
    )
    return MergeEntitiesApplied(applied=True, audit_event_id=event_id)


# ---------------------------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------------------------


def _error(exc: NotesError) -> JSONResponse:
    body = exc.body
    message = str(exc)
    if message and message != exc.code:
        body = {**body, "message": message}
    return JSONResponse(body, status_code=exc.status)


def build_router(cfg: HostConfig) -> APIRouter:
    """POST /hygiene/apply-fix and POST /hygiene/merge-entities for one host config."""
    built = APIRouter()

    def guarded(request: Request, call: Callable[[str], Any]) -> Any:
        user_id = cfg.principal.current_user_id(request)
        try:
            return call(user_id)
        except NotesError as exc:
            return _error(exc)

    @built.post("/hygiene/apply-fix", response_model=ApplyFixDryRun | ApplyFixApplied)
    def post_apply_fix(request: Request, body: ApplyFixBody) -> Any:
        return guarded(
            request,
            lambda user_id: apply_fix(
                cfg, user_id, body.issue_key, body.fix_index, body.confirm_token
            ),
        )

    @built.post(
        "/hygiene/merge-entities", response_model=MergeEntitiesDryRun | MergeEntitiesApplied
    )
    def post_merge_entities(request: Request, body: MergeEntitiesBody) -> Any:
        return guarded(
            request,
            lambda user_id: merge_entities(
                cfg,
                user_id,
                body.entity_type,
                body.keep_id,
                body.merge_ids,
                body.dry_run,
                body.confirm_token,
            ),
        )

    return built
