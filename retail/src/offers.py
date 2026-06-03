"""Next-best-offers — personalised recommendations shown on the home screen.

CIB packages backend's analytical recommendations into ready-to-act offers
at GET /clients/{id}/next-best-offers. Retail just proxies that here so the
home screen can render them and deep-link into the right tab.
"""
from __future__ import annotations

from fastapi import APIRouter

from src.services import BACKEND_URL, CIB_URL, try_get

router = APIRouter()


@router.get("/api/offers/{client_id}")
async def list_offers(client_id: str, limit: int = 5) -> dict:
    """Return packaged offers for the customer; empty list if no source is reachable."""
    cib = await try_get(CIB_URL, f"/clients/{client_id}/next-best-offers",
                        {"limit": str(limit)})
    if cib:
        return {**cib, "source": "cib"}

    # Fallback: raw recommendations from backend (no CIB packaging)
    backend = await try_get(BACKEND_URL, f"/clients/{client_id}/recommendations",
                            {"limit": str(limit)})
    if backend:
        items = backend.get("recommendations", [])
        return {
            "client_id": client_id,
            "name": backend.get("name", ""),
            "segment": backend.get("segment", ""),
            "total": len(items),
            "offers": items,
            "source": "backend",
        }

    return {"client_id": client_id, "total": 0, "offers": [], "source": "none"}
