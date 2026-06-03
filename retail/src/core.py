"""Core proxies: clients & transactions (from backend), products (from cib)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from src.services import backend_get, cib_get

router = APIRouter()


@router.get("/clients")
async def list_clients(request: Request) -> dict:
    return await backend_get("/clients", dict(request.query_params))


@router.get("/transactions/{client_id}")
async def transactions(client_id: str, request: Request) -> dict:
    return await backend_get(f"/transactions/{client_id}", dict(request.query_params))


@router.get("/products")
async def list_products() -> dict:
    """Proxy to the CIB product catalogue."""
    return await cib_get("/products")
