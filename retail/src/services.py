"""Shared configuration and HTTP-helper layer for the retail block.

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

import os
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
