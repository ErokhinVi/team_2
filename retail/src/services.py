"""Shared configuration and HTTP-helper layer for the retail block.

Includes a tiny in-memory TTL cache for the CIB product catalogue, which
several pane endpoints fetch on every request and which changes rarely.


The retail block holds no data of its own — it talks to two neighbours:
  * backend — the data core (clients, transactions, balances, transfers)
  * cib     — business logic (product catalogue + decisions)

Every route module imports the small helper layer below instead of repeating
httpx boilerplate. Two flavours:
  * proxy_get / proxy_post — REQUIRED calls; raise HTTPException on failure.
  * try_get  / try_post    — OPTIONAL calls; return the JSON dict on HTTP 200,
                             or None on any error / non-200 (caller falls back).
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import httpx
from fastapi import HTTPException

# ---- Configuration ----
TEAM_NAME = os.environ.get("TEAM_NAME", "team")
COMMIT = os.environ.get("RENDER_GIT_COMMIT", "local")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8003").rstrip("/")
CIB_URL = os.environ.get("CIB_URL", "http://localhost:8002").rstrip("/")
STATIC_DIR = Path(__file__).resolve().parent / "static"


# ---- Required calls (raise on failure) ----
async def proxy_get(base: str, path: str, who: str, params: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{base}{path}", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{who} недоступен: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    return r.json()


async def proxy_post(base: str, path: str, who: str, payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{base}{path}", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{who} недоступен: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    return r.json()


# ---- Optional calls (return None on failure) ----
async def try_get(base: str, path: str, params: dict | None = None,
                  timeout: float = 10.0) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{base}{path}", params=params)
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        pass
    return None


async def try_post(base: str, path: str, payload: dict,
                   timeout: float = 10.0) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{base}{path}", json=payload)
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        pass
    return None


# ---- Convenience wrappers bound to our two neighbours ----
async def backend_get(path: str, params: dict | None = None) -> dict:
    return await proxy_get(BACKEND_URL, path, "backend", params)


async def cib_get(path: str, params: dict | None = None) -> dict:
    return await proxy_get(CIB_URL, path, "cib", params)


# ---- Cached CIB product catalogue ----
# Five different pane endpoints fetch /products on every request; the catalogue
# changes rarely. Hold it for 60 seconds so we make at most one upstream call
# per minute regardless of how many tabs the customer flips through.
_products_cache: dict = {"data": None, "expires": 0.0}
_products_lock = asyncio.Lock()
PRODUCTS_TTL_SECONDS = 60


async def cached_cib_products() -> dict:
    """Return cib /products, served from a 60-second in-memory cache."""
    now = time.monotonic()
    cached = _products_cache.get("data")
    if cached is not None and _products_cache.get("expires", 0) > now:
        return cached
    async with _products_lock:
        # Re-check after acquiring the lock — another coroutine may have filled it.
        now = time.monotonic()
        cached = _products_cache.get("data")
        if cached is not None and _products_cache.get("expires", 0) > now:
            return cached
        data = await try_get(CIB_URL, "/products") or {}
        _products_cache["data"] = data
        _products_cache["expires"] = now + PRODUCTS_TTL_SECONDS
        return data
