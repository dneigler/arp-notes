"""Hygiene REST routes (K§6.3), mounted by arp_notes.fastapi.build_routers. Owner: H1a (ga-mxal.30).

H1b's fixes router is included here so build_routers needs no further change.
"""

from __future__ import annotations

from fastapi import APIRouter

from arp_notes.hygiene import fixes

router = APIRouter()
router.include_router(fixes.router)
