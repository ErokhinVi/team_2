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
from pydantic import BaseModel

from src.llm import LLMError, ask_llm

TEAM_NAME = os.environ.get("TEAM_NAME", "team")
COMMIT = os.environ.get("RENDER_GIT_COMMIT", "local")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8003").rstrip("/")

# Cashback rates by customer segment
CASHBACK_RATES: dict[str, dict[str, float]] = {
    "mass":          {"groceries": 2.0, "transport": 1.5, "other": 0.5},
    "mass_affluent": {"groceries": 3.0, "transport": 2.0, "other": 1.0},
    "premium":       {"groceries": 5.0, "transport": 3.0, "other": 1.5},
    "private":       {"groceries": 7.0, "transport": 5.0, "other": 2.0},
    "sme":           {"groceries": 2.0, "transport": 2.0, "other": 1.0},
}
DEFAULT_CASHBACK = {"groceries": 2.0, "transport": 1.5, "other": 0.5}

# Credit card limit multipliers by segment (applied to monthly income)
CREDIT_CARD_LIMIT_MULTIPLIER: dict[str, float] = {
    "mass":          2.0,
    "mass_affluent": 4.0,
    "premium":       6.0,
    "private":       10.0,
    "sme":           3.0,
}
CREDIT_CARD_MAX_RISK = 0.60        # standard credit card
CREDIT_CARD_MIN_INCOME = 25_000
SECURED_CARD_MAX_RISK = 0.72       # secured card for borderline customers
SECURED_CARD_MIN_INCOME = 18_000
SECURED_CARD_MAX_LIMIT = 30_000    # hard cap on secured card limit

PRODUCTS = [
    {
        "id": "card-debit-cashback",
        "kind": "card",
        "name": "Дебетовая карта с кэшбэком",
        "cashback_categories": {"groceries": "up to 7%", "transport": "up to 5%", "other": "up to 2%"},
    },
    {
        "id": "card-credit",
        "kind": "credit_card",
        "name": "Кредитная карта",
        "rate_pct": 24.9,
        "grace_period_days": 55,
    },
    {
        "id": "card-credit-secured",
        "kind": "credit_card",
        "name": "Кредитная карта (обеспеченная)",
        "rate_pct": 29.9,
        "grace_period_days": 30,
        "max_limit_rub": SECURED_CARD_MAX_LIMIT,
    },
    {"id": "deposit-3m",  "kind": "deposit", "name": "Депозит 3 месяца",  "rate_pct": 13.0, "term_months": 3,  "early_withdrawal": False},
    {"id": "deposit-6m",  "kind": "deposit", "name": "Депозит 6 месяцев", "rate_pct": 15.0, "term_months": 6,  "early_withdrawal": False},
    {"id": "deposit-12m", "kind": "deposit", "name": "Депозит 12 месяцев","rate_pct": 17.0, "term_months": 12, "early_withdrawal": False},
    {"id": "deposit-flex","kind": "deposit", "name": "Накопительный счёт","rate_pct": 9.5,  "term_months": None,"early_withdrawal": True},
    {"id": "credit-consumer", "kind": "credit", "name": "Потребительский кредит", "rate_pct": 18.9},
]

# Decision thresholds
MAX_RISK_SCORE_STANDARD = 0.55   # for larger amounts (> 6x monthly income)
MAX_RISK_SCORE_SMALL = 0.65      # for smaller amounts (<= 6x monthly income)
MIN_INCOME_RUB = 30_000

app = FastAPI(title="cib — корпоратив и бизнес-логика", version="1.0.0")


class DecideRequest(BaseModel):
    client_id: str
    product_id: str
    amount_rub: float | None = None


class ActivateRequest(BaseModel):
    client_id: str
    product_id: str


class DepositOpenRequest(BaseModel):
    client_id: str
    product_id: str
    amount_rub: float


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "team": TEAM_NAME, "block": "cib",
            "commit": COMMIT, "backend_url": BACKEND_URL, "products": len(PRODUCTS)}


@app.get("/products")
async def products() -> dict:
    return {"total": len(PRODUCTS), "items": PRODUCTS}


@app.post("/credit/decide")
async def credit_decide(req: DecideRequest) -> dict:
    # Fetch customer profile from backend
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BACKEND_URL}/clients/{req.client_id}")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Client not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Backend unavailable")
    customer = resp.json()

    # Find the requested product
    product = next((p for p in PRODUCTS if p["id"] == req.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    # Credit products only
    if product["kind"] != "credit":
        raise HTTPException(status_code=400, detail="Product is not a credit product")

    # Determine applicable risk threshold based on amount vs income
    income = customer.get("income_rub", 0)
    small_loan_ceiling = income * 6  # 6 monthly salaries = "small"
    is_small_amount = req.amount_rub is not None and req.amount_rub <= small_loan_ceiling
    max_risk = MAX_RISK_SCORE_SMALL if is_small_amount else MAX_RISK_SCORE_STANDARD

    # Decision rules
    reasons: list[str] = []
    approved = True

    if customer.get("has_overdue_history"):
        approved = False
        reasons.append("overdue payment history")

    if customer.get("risk_score", 1.0) > max_risk:
        approved = False
        reasons.append(f"risk score too high ({customer['risk_score']:.2f})")

    if customer.get("income_rub", 0) < MIN_INCOME_RUB:
        approved = False
        reasons.append(f"income below minimum ({customer['income_rub']} < {MIN_INCOME_RUB})")

    # Human-readable explanation via LLM (best-effort)
    explanation = ""
    try:
        verdict = "approved" if approved else "declined"
        prompt = (
            f"A bank customer (age {customer.get('age')}, segment {customer.get('segment')}) "
            f"applied for '{product['name']}'. Decision: {verdict}. "
            f"Reasons: {', '.join(reasons) if reasons else 'all checks passed'}. "
            "Write a short, polite one-sentence explanation for the customer in English."
        )
        explanation = await ask_llm(prompt)
    except LLMError:
        explanation = "Decision made based on your financial profile." if approved else \
            "We are unable to approve this application at this time."

    return {
        "client_id": req.client_id,
        "product_id": req.product_id,
        "approved": approved,
        "reasons": reasons,
        "explanation": explanation,
        "customer_name": customer.get("name"),
    }


@app.post("/card/activate")
async def card_activate(req: ActivateRequest) -> dict:
    product = next((p for p in PRODUCTS if p["id"] == req.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["kind"] != "card":
        raise HTTPException(status_code=400, detail="Product is not a card")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BACKEND_URL}/clients/{req.client_id}")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Client not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Backend unavailable")
    customer = resp.json()

    segment = customer.get("segment", "mass")
    rates = CASHBACK_RATES.get(segment, DEFAULT_CASHBACK)

    return {
        "client_id": req.client_id,
        "product_id": req.product_id,
        "activated": True,
        "customer_name": customer.get("name"),
        "segment": segment,
        "cashback_rates_pct": rates,
        "message": (
            f"Card activated for {customer.get('name')}. "
            f"Your cashback: groceries {rates['groceries']}%, "
            f"transport {rates['transport']}%, other {rates['other']}%."
        ),
    }


@app.post("/card/credit-limit")
async def card_credit_limit(req: ActivateRequest) -> dict:
    product = next((p for p in PRODUCTS if p["id"] == req.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["kind"] != "credit_card":
        raise HTTPException(status_code=400, detail="Product is not a credit card")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BACKEND_URL}/clients/{req.client_id}")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Client not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Backend unavailable")
    customer = resp.json()

    income = customer.get("income_rub", 0)
    risk = customer.get("risk_score", 1.0)
    segment = customer.get("segment", "mass")

    hard_decline_reasons: list[str] = []
    if customer.get("has_overdue_history"):
        hard_decline_reasons.append("overdue payment history")

    # Check eligibility for standard card
    standard_eligible = (
        not hard_decline_reasons
        and risk <= CREDIT_CARD_MAX_RISK
        and income >= CREDIT_CARD_MIN_INCOME
    )

    # Check eligibility for secured card (borderline customers)
    secured_eligible = (
        not hard_decline_reasons
        and not standard_eligible
        and risk <= SECURED_CARD_MAX_RISK
        and income >= SECURED_CARD_MIN_INCOME
    )

    if not standard_eligible and not secured_eligible:
        reasons = hard_decline_reasons or [
            f"risk score too high ({risk:.2f})" if risk > SECURED_CARD_MAX_RISK else
            f"income below minimum ({income} < {SECURED_CARD_MIN_INCOME})"
        ]
        return {
            "client_id": req.client_id,
            "product_id": req.product_id,
            "approved": False,
            "limit_rub": 0,
            "reasons": reasons,
            "customer_name": customer.get("name"),
        }

    if standard_eligible:
        multiplier = CREDIT_CARD_LIMIT_MULTIPLIER.get(segment, 2.0)
        raw_limit = income * multiplier * (1.0 - risk)
        limit = round(raw_limit / 10_000) * 10_000
        used_product = product
        note = None
    else:
        # Secured card: small fixed limit, higher rate
        secured = next(p for p in PRODUCTS if p["id"] == "card-credit-secured")
        limit = min(round(income * 0.5 / 5_000) * 5_000, SECURED_CARD_MAX_LIMIT)
        used_product = secured
        note = "Secured card offered due to borderline risk profile. Lower limit, no grace period extensions."

    result = {
        "client_id": req.client_id,
        "product_id": used_product["id"],
        "approved": True,
        "limit_rub": limit,
        "rate_pct": used_product["rate_pct"],
        "grace_period_days": used_product["grace_period_days"],
        "segment": segment,
        "reasons": [],
        "customer_name": customer.get("name"),
    }
    if note:
        result["note"] = note
    return result


@app.post("/deposit/open")
async def deposit_open(req: DepositOpenRequest) -> dict:
    product = next((p for p in PRODUCTS if p["id"] == req.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["kind"] != "deposit":
        raise HTTPException(status_code=400, detail="Product is not a deposit")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BACKEND_URL}/clients/{req.client_id}")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Client not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Backend unavailable")
    customer = resp.json()

    # Minimum amounts by product
    min_amounts = {
        "deposit-3m": 10_000,
        "deposit-6m": 10_000,
        "deposit-12m": 30_000,
        "deposit-flex": 1_000,
    }
    min_amount = min_amounts.get(req.product_id, 10_000)
    if req.amount_rub < min_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Minimum deposit amount is {min_amount} rubles for this product"
        )

    import datetime
    opened_at = datetime.date.today().isoformat()
    term_months = product.get("term_months")
    matures_at = None
    if term_months:
        import datetime as dt
        today = dt.date.today()
        matures_at = today.replace(
            month=((today.month - 1 + term_months) % 12) + 1,
            year=today.year + (today.month - 1 + term_months) // 12,
        ).isoformat()

    interest_rub = round(
        req.amount_rub * product["rate_pct"] / 100 * (term_months or 12) / 12
    )

    return {
        "client_id": req.client_id,
        "product_id": req.product_id,
        "product_name": product["name"],
        "opened": True,
        "amount_rub": req.amount_rub,
        "rate_pct": product["rate_pct"],
        "term_months": term_months,
        "early_withdrawal": product["early_withdrawal"],
        "opened_at": opened_at,
        "matures_at": matures_at,
        "projected_interest_rub": interest_rub,
        "customer_name": customer.get("name"),
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    rows = "".join(
        f"<tr><td>{p['id']}</td><td>{p['kind']}</td><td>{p['name']}</td></tr>"
        for p in PRODUCTS
    )
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<title>cib · Райффайзен</title><style>"
        "body{font-family:system-ui;background:#0c0d10;color:#e8e9ec;padding:32px}"
        "h1{font-weight:500}table{border-collapse:collapse;margin-top:16px}"
        "td,th{border:1px solid #23262f;padding:8px 14px;text-align:left}"
        "</style></head><body>"
        "<h1>cib — корпоратив и бизнес-логика</h1>"
        f"<p>Команда: {TEAM_NAME}. Каталог продуктов:</p>"
        f"<table><tr><th>id</th><th>вид</th><th>название</th></tr>{rows}</table>"
        "</body></html>"
    )
