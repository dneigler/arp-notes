"""build_routers(cfg): the A.2 REST surface as two FastAPI routers. Owner: C3 (ga-mxal.10).

C0 ships only the wiring the contract requires (K§7): the private router mounts
hygiene.routes. C3 adds every A.2 + K§2 endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from arp_notes.config import HostConfig
from arp_notes.hygiene import routes as hygiene_routes


def build_routers(cfg: HostConfig) -> tuple[APIRouter, APIRouter]:
    """-> (private_router, public_router). Private is Bearer-authenticated by the host."""
    private_router = APIRouter()
    public_router = APIRouter()
    private_router.include_router(hygiene_routes.router)
    return private_router, public_router
