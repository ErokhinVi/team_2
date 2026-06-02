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


async def _cib_get(path: str, params: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{CIB_URL}{path}", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"cib недоступен: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    return r.json()


@app.get("/clients")
async def list_clients(request: Request) -> dict:
    return await _backend_get("/clients", dict(request.query_params))


@app.get("/products")
async def products(request: Request) -> dict:
    """Каталог продуктов команды (прокси к cib). Вкладка «Кредиты» берёт отсюда
    кредитные продукты и их ставки."""
    return await _cib_get("/products", dict(request.query_params))


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


@app.post("/api/credit-apply")
async def api_credit_apply(payload: dict) -> dict:
    """Заявка на кредит — оркестрация двух соседей.

    1. Берём карточку клиента в backend (доход, просрочки) — подтверждаем, что
       клиент существует, и показываем контекст в ответе.
    2. Просим cib вынести решение по заявке (cib сам дотянется в backend за
       деталями). Пока cib не опубликовал ручку решения — отдаём дружелюбный
       «ещё не подключено», чтобы UI не падал.
    """
    payload = payload or {}
    client_id = payload.get("client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="не указан клиент")

    client = await _backend_get(f"/clients/{client_id}")
    client_view = {
        "id": client.get("id"),
        "name": client.get("name"),
        "segment": client.get("segment"),
        "income_rub": client.get("income_rub"),
        "balance_rub": client.get("balance_rub"),
        "has_overdue_history": client.get("has_overdue_history"),
    }

    decide_body = {
        "client_id": client_id,
        "product_id": payload.get("product_id"),
        "amount_rub": payload.get("amount_rub"),
        "term_months": payload.get("term_months"),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(f"{CIB_URL}/credit/decide", json=decide_body)
    except httpx.HTTPError as exc:
        return {"decision": "pending_integration", "client": client_view,
                "message": f"блок решений (cib) недоступен: {exc}"}
    if r.status_code == 404:
        return {"decision": "pending_integration", "client": client_view,
                "message": "блок решений (cib) ещё не опубликовал ручку /credit/decide"}
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:300])

    return {"client": client_view, "result": r.json()}
