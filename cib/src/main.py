"""Блок cib — корпоратив и бизнес-логика банка команды.

Каталог продуктов и (в рамках задачи) логика кредитного решения.
За данными клиента ходит в backend по BACKEND_URL. Логику решения
(POST /credit/decide) и кредитный продукт добавляет владелец блока.
Хелпер src/llm.py — для человеческого объяснения решения.
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.llm import LLMError, ask_llm

TEAM_NAME = os.environ.get("TEAM_NAME", "team")
COMMIT = os.environ.get("RENDER_GIT_COMMIT", "local")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8003").rstrip("/")

CREDIT_PRODUCT = {
    "id": "credit-card-classic",
    "kind": "credit",
    "name": "Кредитная карта Classic",
    "segment": "mass",
    "rate_pct": 21.9,
    "limit_min_rub": 30_000,
    "limit_max_rub": 500_000,
    "grace_days": 55,
}

PRODUCTS = [
    {"id": "card-debit", "kind": "card", "name": "Дебетовая карта", "segment": "mass"},
    {"id": "deposit-base", "kind": "deposit", "name": "Срочный депозит", "rate_pct": 14.0},
    CREDIT_PRODUCT,
]

app = FastAPI(title="cib — корпоратив и бизнес-логика", version="1.1.0")


class CreditRequest(BaseModel):
    client_id: str = Field(..., description="id клиента из backend")
    amount_rub: int = Field(..., gt=0, description="запрашиваемая сумма кредита в рублях")


class CreditDecision(BaseModel):
    approved: bool
    client_id: str
    requested_rub: int
    approved_rub: int
    rate_pct: float | None
    product_id: str | None
    reason: str
    explanation: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "team": TEAM_NAME, "block": "cib",
            "commit": COMMIT, "backend_url": BACKEND_URL, "products": len(PRODUCTS)}


@app.get("/products")
async def products() -> dict:
    return {"total": len(PRODUCTS), "items": PRODUCTS}


async def _fetch_client(client_id: str) -> dict:
    url = f"{BACKEND_URL}/clients/{client_id}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"backend недоступен: {exc}") from exc
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    if resp.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f"backend вернул {resp.status_code}")
    return resp.json()


def _score(client: dict, amount_rub: int) -> tuple[bool, int, str]:
    """Простое решение: считаем ежемесячный платёж как 1/24 от суммы.

    Одобряем, если доход не меньше трёх таких платежей, нет просрочек и баланс
    положительный. Если доход средний — режем лимит. Возвращает
    (approved, approved_amount, reason).
    """
    income = int(client.get("income_rub") or 0)
    balance = int(client.get("balance_rub") or 0)
    overdue = bool(client.get("has_overdue_history"))

    if overdue:
        return False, 0, "В истории клиента есть просрочки"
    if balance < 0:
        return False, 0, "Текущий баланс отрицательный"
    if income <= 0:
        return False, 0, "Доход клиента не подтверждён"

    monthly_payment = amount_rub / 24
    if income < monthly_payment * 3:
        capped = int(min(amount_rub, income * 24 // 3))
        if capped < CREDIT_PRODUCT["limit_min_rub"]:
            return False, 0, "Доход не покрывает минимальный лимит по продукту"
        return True, capped, "Сумма скорректирована под доход клиента"

    capped = min(max(amount_rub, CREDIT_PRODUCT["limit_min_rub"]),
                 CREDIT_PRODUCT["limit_max_rub"])
    return True, capped, "Клиент подходит по доходу и кредитной истории"


@app.post("/credit/decide", response_model=CreditDecision)
async def credit_decide(req: CreditRequest) -> CreditDecision:
    client = await _fetch_client(req.client_id)
    approved, approved_rub, reason = _score(client, req.amount_rub)

    name = client.get("name", "клиент")
    try:
        explanation = await ask_llm(
            (
                f"Клиент {name} попросил кредит на {req.amount_rub} рублей. "
                f"Решение банка: {'одобрено' if approved else 'отказ'} — {reason}. "
                "Одним коротким абзацем (3-4 предложения), без жаргона и без чисел "
                "из условий, объясни клиенту это решение по-человечески."
            ),
            system="Ты вежливый сотрудник Райффайзенбанка.",
            max_tokens=180,
            temperature=0.5,
        )
    except LLMError:
        explanation = (
            "Спасибо за заявку. Решение принято на основе вашего профиля; "
            "подробное пояснение мы пришлём отдельным сообщением."
        )

    return CreditDecision(
        approved=approved,
        client_id=req.client_id,
        requested_rub=req.amount_rub,
        approved_rub=approved_rub,
        rate_pct=CREDIT_PRODUCT["rate_pct"] if approved else None,
        product_id=CREDIT_PRODUCT["id"] if approved else None,
        reason=reason,
        explanation=explanation.strip(),
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    rows = "".join(
        f"<tr><td>{p['id']}</td><td>{p['kind']}</td><td>{p['name']}</td></tr>"
        for p in PRODUCTS
    )
    credit = CREDIT_PRODUCT
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<title>cib · Райффайзен</title><style>"
        "body{font-family:system-ui;background:#0c0d10;color:#e8e9ec;padding:32px;"
        "max-width:880px;margin:0 auto}"
        "h1,h2{font-weight:500}h2{margin-top:32px}"
        "table{border-collapse:collapse;margin-top:16px;width:100%}"
        "td,th{border:1px solid #23262f;padding:8px 14px;text-align:left}"
        ".card{background:#14161b;border:1px solid #23262f;padding:18px 22px;"
        "border-radius:8px;margin-top:16px}"
        ".pill{display:inline-block;background:#ffcc00;color:#0c0d10;"
        "padding:2px 10px;border-radius:999px;font-size:12px;margin-left:8px}"
        "</style></head><body>"
        "<h1>cib — корпоратив и бизнес-логика</h1>"
        f"<p>Команда: {TEAM_NAME}. Каталог продуктов:</p>"
        f"<table><tr><th>id</th><th>вид</th><th>название</th></tr>{rows}</table>"
        "<h2>Кредитная карта Classic <span class='pill'>new</span></h2>"
        "<div class='card'>"
        f"<p>Ставка {credit['rate_pct']}% годовых. Льготный период "
        f"{credit['grace_days']} дней.</p>"
        f"<p>Лимит: от {credit['limit_min_rub']:,} ₽ до "
        f"{credit['limit_max_rub']:,} ₽ — зависит от подтверждённого дохода.</p>"
        "<p>Решение по заявке выдаёт ручка <code>POST /credit/decide</code>: "
        "она спрашивает у backend профиль клиента, считает посильный платёж "
        "и возвращает ответ с человеческим объяснением.</p>"
        "</div>"
        "</body></html>"
    )
