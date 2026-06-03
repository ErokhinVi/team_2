"""Блок retail — клиентский мобильный банк команды.

UI плюс тонкий слой: за данными ходит в backend, за кредитным решением — в cib.
Своих данных не держит. Вкладку «Кредиты» и /api/credit-apply (оркестрацию
cib + backend) добавляет владелец блока в рамках задачи.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

TEAM_NAME = os.environ.get("TEAM_NAME", "team")
COMMIT = os.environ.get("RENDER_GIT_COMMIT", "local")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8003").rstrip("/")
CIB_URL = os.environ.get("CIB_URL", "http://localhost:8002").rstrip("/")

app = FastAPI(title="retail — мобильный банк", version="1.0.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "team": TEAM_NAME, "block": "retail",
            "commit": COMMIT, "backend_url": BACKEND_URL, "cib_url": CIB_URL}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    f = STATIC_DIR / "index.html"
    return f.read_text(encoding="utf-8") if f.exists() else "<h1>Розница</h1>"


async def _backend_get(path: str, params: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{BACKEND_URL}{path}", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"backend недоступен: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    return r.json()


@app.get("/clients")
async def list_clients(request: Request) -> dict:
    return await _backend_get("/clients", dict(request.query_params))


@app.get("/transactions/{client_id}")
async def transactions(client_id: str, request: Request) -> dict:
    return await _backend_get(f"/transactions/{client_id}", dict(request.query_params))


@app.post("/api/transfer")
async def api_transfer(payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{BACKEND_URL}/api/transfer", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"backend недоступен: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    return r.json()


# ---- Loan products (from CIB) ----

async def _cib_get(path: str, params: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{CIB_URL}{path}", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"cib недоступен: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    return r.json()


@app.get("/products")
async def list_products() -> dict:
    """Proxy to CIB product catalogue — returns loan/deposit products."""
    return await _cib_get("/products")


@app.post("/api/credit-apply")
async def credit_apply(payload: dict) -> dict:
    """Orchestrate a loan application.

    Sends client_id + product_id to CIB POST /credit/decide.
    CIB fetches the customer profile from backend on its own and returns
    {approved, reasons, explanation, customer_name}.
    If CIB is unreachable, falls back to a simple local heuristic.
    """
    client_id = payload.get("client_id")
    product_id = payload.get("product_id")
    amount = payload.get("amount_rub", 0)

    if not client_id or not product_id:
        raise HTTPException(status_code=400, detail="client_id and product_id required")

    # Ask CIB for credit decision (CIB fetches customer data itself)
    decision_payload = {
        "client_id": client_id,
        "product_id": product_id,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{CIB_URL}/credit/decide", json=decision_payload)
        if r.status_code == 200:
            cib = r.json()
            return {
                "status": "approved" if cib.get("approved") else "declined",
                "client_id": cib.get("client_id", client_id),
                "product_id": cib.get("product_id", product_id),
                "amount_rub": amount,
                "reason": cib.get("explanation", ""),
                "reasons": cib.get("reasons", []),
                "customer_name": cib.get("customer_name", ""),
                "source": "cib",
            }
        # CIB returned an error — fall through to local heuristic
    except httpx.HTTPError:
        pass  # CIB unreachable — fall through to local heuristic

    # Fallback: simple heuristic when CIB is not reachable
    customer = await _backend_get(f"/clients/{client_id}")
    income = customer.get("income_rub", 0)
    has_overdue = customer.get("has_overdue_history", False)

    approved = (income >= 30_000 and not has_overdue and amount <= income * 12)
    max_amount = income * 12 if not has_overdue else 0

    return {
        "status": "approved" if approved else "declined",
        "client_id": client_id,
        "product_id": product_id,
        "amount_rub": amount,
        "max_amount_rub": max_amount,
        "reason": (
            "Income and history OK" if approved
            else "Insufficient income or overdue history"
        ),
        "source": "retail-heuristic",
    }
