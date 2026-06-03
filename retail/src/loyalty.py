"""Loyalty endpoint — proxies CIB GET /clients/{id}/loyalty so the home
screen can show a 'Your rewards' card with the customer's tier and next-tier
hint. Returns a minimal stub when CIB is unreachable so the UI degrades
gracefully without showing an error."""
from __future__ import annotations

from fastapi import APIRouter

from src.services import CIB_URL, try_get

router = APIRouter()


@router.get("/api/loyalty/{client_id}")
async def loyalty_info(client_id: str) -> dict:
    cib = await try_get(CIB_URL, f"/clients/{client_id}/loyalty", timeout=5.0)
    if cib:
        return {**cib, "source": "cib"}
    return {
        "client_id": client_id,
        "tier": "standard",
        "perks": [],
        "next_tier": None,
        "next_tier_hint": "",
        "products_count": 0,
        "source": "unavailable",
    }
