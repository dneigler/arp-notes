"""The kit against the C3 reference host: in-process (--asgi) and over HTTP (--base-url)."""

from __future__ import annotations

from arp_notes_conformance import suite
from fastapi import FastAPI
from ref_host import TOKEN


def test_green_in_process(host_app: FastAPI) -> None:
    report = suite(app=host_app, token=TOKEN, raise_on_failure=False)
    print("\n".join(report.lines()))
    assert report.ok


def test_green_over_http(live_url: str) -> None:
    report = suite(base_url=live_url, token=TOKEN, raise_on_failure=False)
    print("\n".join(report.lines()))
    assert report.ok
