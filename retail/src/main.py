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
from fastapi.responses import HTMLResponse, JSONResponse

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


async def _post_json(base_url: str, path: str, payload: dict) -> tuple[int, dict]:
    """Call a neighbouring block and keep its status and JSON response intact."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{base_url}{path}", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"сервис недоступен: {exc}")
    try:
        body = r.json()
    except ValueError:
        body = {"detail": r.text[:300]}
    return r.status_code, body if isinstance(body, dict) else {"detail": body}


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


@app.post("/api/credit-apply")
async def api_credit_apply(payload: dict):
    """Create an application in backend, then ask CIB for its decision."""
    client_id = str(payload.get("client_id", "")).strip()
    product_id = str(payload.get("product_id", "credit-consumer")).strip()
    try:
        amount_rub = int(payload.get("amount_rub"))
        term_months = int(payload.get("term_months"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="сумма и срок обязательны")
    if not client_id or not product_id:
        raise HTTPException(status_code=422, detail="клиент и продукт обязательны")
    if not 50_000 <= amount_rub <= 1_500_000:
        raise HTTPException(status_code=422, detail="сумма должна быть от 50 000 до 1 500 000 ₽")
    if not 6 <= term_months <= 60:
        raise HTTPException(status_code=422, detail="срок должен быть от 6 до 60 месяцев")

    application_status, application = await _post_json(
        BACKEND_URL,
        "/credit-applications",
        {"client_id": client_id, "product_id": product_id,
         "amount_rub": amount_rub, "term_months": term_months},
    )
    if application_status >= 400:
        return JSONResponse(status_code=application_status, content=application)
    application_id = application.get("application_id")
    if not application_id:
        raise HTTPException(status_code=502, detail="backend не вернул номер заявки")

    try:
        decision_status, decision = await _post_json(
            CIB_URL, "/credit/decide", {"application_id": application_id}
        )
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"reason_code": "service_unavailable", "detail": "не удалось связаться с CIB",
                     "application_id": application_id},
        )
    decision.setdefault("application_id", application_id)
    if decision_status == 409 and decision.get("reason_code") == "client_data_incomplete":
        return JSONResponse(status_code=409, content=decision)
    if decision_status >= 400:
        return JSONResponse(status_code=decision_status, content=decision)
    return decision
