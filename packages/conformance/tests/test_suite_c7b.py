"""C7b (ga-mxal.38): the attachment, enrichment, export, MCP and hygiene checks.

Three things are shown. The reference host is green with exactly the skips it should have (so a
check cannot pass vacuously). Hosts with other policies are green too, with the checks they make
moot skipped for a stated reason. And the checks have teeth: each one fails against a host that
breaks the rule it guards.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import ref_host
from arp_notes import attachments, export, hygiene, repo, review
from arp_notes.models import DismissResult
from arp_notes.ports import Policy
from arp_notes.testing.fakedb import FakeDb
from arp_notes_conformance import Report, suite
from ref_host import TOKEN, make_app

C7B_GROUPS = ("attachments", "enrich", "export", "mcp", "hygiene")
EXPECTED_SKIPS = {
    "attachments.mime_allowlist": "accepts any MIME type",
    "attachments.refused_when_off": "takes attachments",
    "export.disabled_is_refused": "allows export",
    "hygiene.merge_entities_dry_run": "does not merge entities",
}


def run(app: Any, *only: str, **kw: Any) -> Report:
    return suite(app=app, token=TOKEN, only=list(only) or None, raise_on_failure=False, **kw)


def statuses(report: Report) -> dict[str, str]:
    return {o.name: o.status for o in report.outcomes}


def detail(report: Report, name: str) -> str:
    return next(o.detail for o in report.outcomes if o.name == name)


@pytest.fixture
def make(notes_db: FakeDb, tmp_path: Path) -> Callable[..., Any]:
    def build(**kw: Any) -> Any:
        return make_app(notes_db, tmp_path / "blobs", **kw)

    return build


# -- the reference host ---------------------------------------------------------------------


def test_reference_host_is_green_and_skips_only_what_it_should(make: Callable[..., Any]) -> None:
    report = run(make(), *C7B_GROUPS)
    assert report.ok, "\n".join(report.lines())
    skipped = {o.name: o.detail for o in report.of("skipped")}
    assert set(skipped) == set(EXPECTED_SKIPS), skipped
    for name, reason in EXPECTED_SKIPS.items():
        assert reason in skipped[name]
    assert len(report.of("passed")) >= 25


# -- other policies: green, with the moot checks skipped ------------------------------------


def test_host_without_attachments(make: Callable[..., Any]) -> None:
    report = run(make(policy=Policy(attachments=False)), *C7B_GROUPS)
    assert report.ok, "\n".join(report.lines())
    got = statuses(report)
    assert got["attachments.refused_when_off"] == "passed"
    for name in (
        "upload_roundtrip",
        "hash_mismatch",
        "signed_content",
        "oversize",
        "app_note_paste",
    ):
        assert got[f"attachments.{name}"] == "skipped"
        assert "attachments=false" in detail(report, f"attachments.{name}")
    assert got["export.round_trip_attachments"] == "skipped"
    assert got["export.round_trip_app_note"] == "passed"
    assert got["mcp.attachment_upload_tool"] == "passed"


def test_host_with_a_pdf_only_allowlist(make: Callable[..., Any]) -> None:
    report = run(make(policy=Policy(mime_allowlist=["application/pdf"])), *C7B_GROUPS)
    assert report.ok, "\n".join(report.lines())
    got = statuses(report)
    assert got["attachments.mime_allowlist"] == "passed"
    assert got["attachments.upload_roundtrip"] == "passed"
    assert got["attachments.summary_thumbnail"] == "skipped"
    assert got["export.round_trip_attachments"] == "passed"


def test_host_with_export_off(make: Callable[..., Any]) -> None:
    report = run(make(policy=Policy(export=False)), *C7B_GROUPS)
    assert report.ok, "\n".join(report.lines())
    got = statuses(report)
    assert got["export.disabled_is_refused"] == "passed"
    assert {got[n] for n in got if n.startswith("export.") and "disabled" not in n} == {"skipped"}


def test_host_with_hygiene_off(make: Callable[..., Any]) -> None:
    report = run(make(policy=Policy(hygiene=False)), *C7B_GROUPS)
    assert report.ok, "\n".join(report.lines())
    got = statuses(report)
    assert got["hygiene.block_only_when_asked"] == "skipped"
    assert "hygiene=false" in detail(report, "hygiene.block_only_when_asked")
    assert got["hygiene.dismiss_hides_the_issue"] == "skipped"
    assert got["mcp.list_notes_carries_hygiene"] == "passed"
    assert got["mcp.tools_list"] == "passed"


def test_host_that_does_not_propose_on_sync(make: Callable[..., Any]) -> None:
    report = run(make(policy=Policy(propose_on_sync="off")), "enrich", "review")
    assert report.ok, "\n".join(report.lines())


# -- MCP location ---------------------------------------------------------------------------


def test_host_without_mcp_skips_mcp_checks_and_says_where_it_looked(
    make: Callable[..., Any],
) -> None:
    report = run(make(mcp_path=None), "mcp")
    assert report.ok
    assert {o.status for o in report.outcomes} == {"skipped"}
    reason = report.outcomes[0].detail
    assert "/mcp" in reason and "ARP_NOTES_MCP_URL" in reason


def test_mcp_url_from_the_environment(
    make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make(mcp_path="/somewhere/else")
    assert statuses(run(app, "mcp.tools_list")) == {"mcp.tools_list": "skipped"}
    monkeypatch.setenv("ARP_NOTES_MCP_URL", "/somewhere/else")
    assert statuses(run(app, "mcp.tools_list")) == {"mcp.tools_list": "passed"}


def test_a_wrong_explicit_mcp_url_is_a_failure_not_a_skip(
    make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARP_NOTES_MCP_URL", "/not-mcp")
    report = run(make(), "mcp.tools_list")
    assert statuses(report) == {"mcp.tools_list": "failed"}
    assert "does not speak MCP" in detail(report, "mcp.tools_list")


# -- the checks have teeth ------------------------------------------------------------------


def _accept_any_signature(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(attachments.hmac, "compare_digest", lambda a, b: True)


def _tickets_never_spent(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(repo, "consume_ticket", lambda *a, **k: True)


def _no_policy_at_all(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(attachments, "_check_policy", lambda cfg, mime, size: None)


def _forget_deferred(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(review, "apply_confirm", lambda *a, **k: {"review_pending": 0})


def _drop_rejections(mp: pytest.MonkeyPatch) -> None:
    confirm_links = repo.confirm_links

    def without_rejections(cfg: Any, user_id: str, note_id: int, body: Any) -> Any:
        return confirm_links(cfg, user_id, note_id, body.model_copy(update={"rejected": []}))

    mp.setattr(repo, "confirm_links", without_rejections)


def _dismiss_does_nothing(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(hygiene, "dismiss", lambda *a, **k: DismissResult(dismissed=True))


def _export_without_a_header(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(export, "_header_entries", lambda note, exported_at: [])


def _export_adds_a_line(mp: pytest.MonkeyPatch) -> None:
    export_note = export.export_note

    def padded(*a: Any, **k: Any) -> Any:
        markdown, manifest = export_note(*a, **k)
        return markdown + "\n", manifest

    mp.setattr(export, "export_note", padded)


def _drop_a_hygiene_tool(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(ref_host, "TOOLS", [t for t in ref_host.TOOLS if t.name != "apply_fix"])


TEETH = [
    ("attachments.signed_content", _accept_any_signature, "refused with 403"),
    ("attachments.ticket_single_use", _tickets_never_spent, "replay"),
    ("attachments.oversize", _no_policy_at_all, "413"),
    ("enrich.deferred_keeps_review_pending", _forget_deferred, "review_pending"),
    ("enrich.rejection_persists_and_suppresses", _drop_rejections, "links_rejected"),
    ("hygiene.dismiss_hides_the_issue", _dismiss_does_nothing, "dismissed issue"),
    ("export.app_note_markdown", _export_without_a_header, "arp_id"),
    ("export.round_trip_attachments", _export_adds_a_line, "export of an import"),
    ("mcp.tools_list", _drop_a_hygiene_tool, "apply_fix"),
]


@pytest.mark.parametrize(("name", "break_it", "mentions"), TEETH, ids=[t[0] for t in TEETH])
def test_check_fails_against_a_host_that_breaks_the_rule(
    name: str,
    break_it: Callable[[pytest.MonkeyPatch], None],
    mentions: str,
    make: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert statuses(run(make(), name)) == {name: "passed"}  # green before it is broken
    break_it(monkeypatch)
    report = run(make(), name)
    assert statuses(report) == {name: "failed"}, "\n".join(report.lines())
    assert mentions in detail(report, name)


def test_declared_off_but_accepting_uploads_fails(
    make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make(policy=Policy(attachments=False))
    assert statuses(run(app, "attachments.refused_when_off")) == {
        "attachments.refused_when_off": "passed"
    }
    _no_policy_at_all(monkeypatch)
    report = run(app, "attachments.refused_when_off")
    assert statuses(report) == {"attachments.refused_when_off": "failed"}
    assert "capabilities.attachments is false" in detail(report, "attachments.refused_when_off")
