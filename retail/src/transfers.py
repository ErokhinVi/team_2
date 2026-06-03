"""Money transfers (proxied to the backend)."""
from __future__ import annotations

from fastapi import APIRouter

from src.services import BACKEND_URL, proxy_post

router = APIRouter()


@router.post("/api/transfer")
async def api_transfer(payload: dict) -> dict:
    return await proxy_post(BACKEND_URL, "/api/transfer", "backend", payload)
