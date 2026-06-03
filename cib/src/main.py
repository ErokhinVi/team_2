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
    # Investment products. risk_level 1 (lowest) .. 5 (highest).
    {"id": "inv-ofz",        "kind": "investment", "subtype": "bond",  "name": "Гособлигации (ОФЗ)",        "risk_level": 1, "expected_return_pct": 13.0, "min_investment_rub": 10_000},
    {"id": "inv-corp-bond",  "kind": "investment", "subtype": "bond",  "name": "Фонд корпоративных облигаций", "risk_level": 2, "expected_return_pct": 16.0, "min_investment_rub": 10_000},
    {"id": "inv-etf-index",  "kind": "investment", "subtype": "etf",   "name": "ETF на индекс Мосбиржи",    "risk_level": 3, "expected_return_pct": 18.0, "min_investment_rub": 5_000},
    {"id": "inv-equity-fund","kind": "investment", "subtype": "fund",  "name": "Фонд акций",                 "risk_level": 3, "expected_return_pct": 19.0, "min_investment_rub": 5_000},
    {"id": "inv-bluechip",   "kind": "investment", "subtype": "stock", "name": "Голубые фишки (акции)",      "risk_level": 4, "expected_return_pct": 22.0, "min_investment_rub": 30_000},
    {"id": "inv-growth",     "kind": "investment", "subtype": "stock", "name": "Акции роста",                "risk_level": 5, "expected_return_pct": 28.0, "min_investment_rub": 50_000},
]

# Human-readable investor risk profile names by max acceptable risk level.
RISK_LEVEL_NAMES = {
    1: "conservative",
    2: "cautious",
    3: "balanced",
    4: "growth",
    5: "aggressive",
}

# Bridge between CIB's risk-rated investment products and backend's tradeable
# instrument symbols (GET /instruments). Symbols on the right are PROVISIONAL —
# confirm each against backend's live catalogue and adjust. If a symbol is not
# found in the catalogue, /investment/order-plan returns the plan without a qty
# and flags it, rather than producing a wrong order.
INVESTMENT_SYMBOL_MAP = {
    "inv-ofz":         "OFZ",      # government bonds
    "inv-corp-bond":   "RUCORP",   # corporate bond fund
    "inv-etf-index":   "TMOS",     # Moscow Exchange index ETF
    "inv-equity-fund": "EQMX",     # broad equity fund
    "inv-bluechip":    "SBER",     # blue-chip representative
    "inv-growth":      "YDEX",     # growth representative
}


def investor_profile(customer: dict) -> dict:
    """Derive an investment suitability profile from a customer's circumstances.

    Uses time horizon (age), capacity to absorb loss (income, balance) and
    segment as a sophistication proxy. Deliberately NOT credit risk_score —
    that measures repayment, not investment appetite. Returns the maximum
    investment risk_level (1..5) the customer may be offered.
    """
    age = customer.get("age", 99)
    income = customer.get("income_rub", 0)
    balance = customer.get("balance_rub", 0)

    points = 0
    # Time horizon — younger investors can ride out volatility
    if age < 35:
        points += 2
    elif age <= 55:
        points += 1
    # Capacity — a financial buffer means a loss won't be catastrophic
    if balance >= 1_000_000:
        points += 2
    elif balance >= 200_000:
        points += 1
    if income >= 150_000:
        points += 1

    max_risk = max(1, min(5, points))

    # Regulatory floor: a thin balance can't bear investment losses — protect.
    if balance < 50_000:
        max_risk = 1

    return {
        "profile": RISK_LEVEL_NAMES[max_risk],
        "max_risk_level": max_risk,
        "age": age,
        "income_rub": income,
        "balance_rub": balance,
    }

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


class DepositWithdrawRequest(BaseModel):
    deposit_id: str
    early: bool = False


class SuitabilityRequest(BaseModel):
    client_id: str
    product_id: str
    amount_rub: float | None = None


class RecommendRequest(BaseModel):
    client_id: str


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

    # Find the requested product. Accept retail's alias "credit-card" for the
    # credit card, so eligibility checks from the app resolve correctly.
    product_id = req.product_id
    if product_id == "credit-card":
        product_id = "card-credit"
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    # Credit-type products only (consumer loans and credit cards)
    if product["kind"] not in ("credit", "credit_card"):
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

    # Record the holding on the customer's profile so it actually sticks.
    # Best-effort: a transient failure shouldn't block the activation.
    recorded = await _record_product(
        req.client_id, req.product_id, {"cashback_rates_pct": rates, "segment": segment}
    )

    return {
        "client_id": req.client_id,
        "product_id": req.product_id,
        "activated": True,
        "recorded": recorded,
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

    import calendar
    import datetime

    today = datetime.date.today()
    opened_at = today.isoformat()
    term_months = product.get("term_months")
    matures_at = None
    if term_months:
        total = today.month - 1 + term_months
        year = today.year + total // 12
        month = total % 12 + 1
        # Clamp the day to the last valid day of the target month
        last_day = calendar.monthrange(year, month)[1]
        day = min(today.day, last_day)
        matures_at = datetime.date(year, month, day).isoformat()

    interest_rub = round(
        req.amount_rub * product["rate_pct"] / 100 * (term_months or 12) / 12
    )

    # Move the money: call backend to debit the balance and book the deposit.
    payload = {
        "client_id": req.client_id,
        "product": req.product_id,
        "amount_rub": req.amount_rub,
        "term_months": term_months,
        "rate_pct": product["rate_pct"],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        mv = await client.post(f"{BACKEND_URL}/api/deposits", json=payload)
    if mv.status_code == 400:
        # Insufficient funds (or similar) — surface the backend's clear reason.
        detail = mv.json().get("detail", "Deposit could not be opened")
        raise HTTPException(status_code=400, detail=detail)
    if mv.status_code == 404:
        raise HTTPException(status_code=404, detail="Client not found")
    if mv.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="Backend could not open the deposit")
    moved = mv.json()

    return {
        "client_id": req.client_id,
        "product_id": req.product_id,
        "product_name": product["name"],
        "opened": True,
        "deposit_id": moved.get("deposit_id"),
        "amount_rub": req.amount_rub,
        "rate_pct": product["rate_pct"],
        "term_months": term_months,
        "early_withdrawal": product["early_withdrawal"],
        "opened_at": opened_at,
        # Prefer backend's authoritative maturity and balance; fall back to ours.
        "matures_at": moved.get("matures_at", matures_at),
        "new_balance_rub": moved.get("new_balance_rub"),
        "projected_interest_rub": interest_rub,
        "customer_name": customer.get("name"),
    }


@app.post("/deposit/withdraw")
async def deposit_withdraw(req: DepositWithdrawRequest) -> dict:
    """Close a deposit and return the money (+ interest) to the customer."""
    body = {"early": req.early} if req.early else {}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BACKEND_URL}/api/deposits/{req.deposit_id}/withdraw", json=body
        )
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Deposit not found")
    if resp.status_code == 400:
        detail = resp.json().get("detail", "Deposit could not be withdrawn")
        raise HTTPException(status_code=400, detail=detail)
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="Backend could not withdraw the deposit")
    return resp.json()


async def _fetch_customer(client_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BACKEND_URL}/clients/{client_id}")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Client not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Backend unavailable")
    return resp.json()


async def _record_product(client_id: str, product: str, details: dict | None = None) -> bool:
    """Record a product onto the customer's profile in backend. Best-effort:
    returns True if backend accepted it, False otherwise (never raises)."""
    payload = {"product": product, "source": "cib"}
    if details:
        payload["details"] = details
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/clients/{client_id}/products", json=payload
            )
        return resp.status_code in (200, 201)
    except httpx.HTTPError:
        return False


async def _fetch_instruments() -> list[dict]:
    """Backend's tradeable catalogue (GET /instruments). Empty list if unreachable."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/instruments")
        if resp.status_code == 200:
            return resp.json().get("items", [])
    except httpx.HTTPError:
        pass
    return []


def _suitability_check(product: dict, prof: dict, amount_rub: float | None) -> list[str]:
    """Return a list of reasons the product is unsuitable. Empty list == suitable."""
    reasons: list[str] = []

    if product["risk_level"] > prof["max_risk_level"]:
        reasons.append(
            f"product risk level {product['risk_level']} exceeds the customer's "
            f"suitable level {prof['max_risk_level']} ({prof['profile']} profile)"
        )

    if prof["balance_rub"] < product["min_investment_rub"]:
        reasons.append(
            f"balance below product minimum ({prof['balance_rub']} < {product['min_investment_rub']})"
        )

    if amount_rub is not None:
        if amount_rub < product["min_investment_rub"]:
            reasons.append(
                f"amount below product minimum ({amount_rub} < {product['min_investment_rub']})"
            )
        # Concentration guard: don't let a customer put more than 50% of their
        # balance into a single higher-risk (level >= 4) investment.
        if product["risk_level"] >= 4 and amount_rub > prof["balance_rub"] * 0.5:
            reasons.append("amount exceeds 50% of balance for a high-risk product (concentration limit)")

    return reasons


@app.post("/investment/suitability")
async def investment_suitability(req: SuitabilityRequest) -> dict:
    product = next((p for p in PRODUCTS if p["id"] == req.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["kind"] != "investment":
        raise HTTPException(status_code=400, detail="Product is not an investment")

    customer = await _fetch_customer(req.client_id)
    prof = investor_profile(customer)

    reasons = _suitability_check(product, prof, req.amount_rub)
    suitable = not reasons

    # Suggest suitable alternatives if this product doesn't fit
    alternatives = [
        {"id": p["id"], "name": p["name"], "risk_level": p["risk_level"],
         "expected_return_pct": p["expected_return_pct"]}
        for p in PRODUCTS
        if p["kind"] == "investment"
        and p["risk_level"] <= prof["max_risk_level"]
        and prof["balance_rub"] >= p["min_investment_rub"]
    ]
    alternatives.sort(key=lambda p: p["expected_return_pct"], reverse=True)

    return {
        "client_id": req.client_id,
        "product_id": req.product_id,
        "product_name": product["name"],
        "suitable": suitable,
        "reasons": reasons,
        "investor_profile": prof["profile"],
        "max_risk_level": prof["max_risk_level"],
        "product_risk_level": product["risk_level"],
        "suitable_alternatives": [] if suitable else alternatives,
        "customer_name": customer.get("name"),
    }


@app.post("/investment/recommend")
async def investment_recommend(req: RecommendRequest) -> dict:
    customer = await _fetch_customer(req.client_id)
    prof = investor_profile(customer)

    recommended = [
        {"id": p["id"], "name": p["name"], "subtype": p["subtype"],
         "risk_level": p["risk_level"], "expected_return_pct": p["expected_return_pct"],
         "min_investment_rub": p["min_investment_rub"]}
        for p in PRODUCTS
        if p["kind"] == "investment"
        and p["risk_level"] <= prof["max_risk_level"]
        and prof["balance_rub"] >= p["min_investment_rub"]
    ]
    recommended.sort(key=lambda p: p["expected_return_pct"], reverse=True)

    return {
        "client_id": req.client_id,
        "customer_name": customer.get("name"),
        "investor_profile": prof["profile"],
        "max_risk_level": prof["max_risk_level"],
        "total": len(recommended),
        "items": recommended,
    }


@app.post("/investment/order-plan")
async def investment_order_plan(req: SuitabilityRequest) -> dict:
    """Bridge a CIB investment product to an executable backend order.

    Runs the suitability check, then maps the product to a tradeable symbol and
    prices the order against backend's live catalogue, computing how many units
    fit within the requested amount. Retail takes the returned `order` and posts
    it to backend `POST /clients/{client_id}/orders`.
    """
    if req.amount_rub is None or req.amount_rub <= 0:
        raise HTTPException(status_code=400, detail="amount_rub is required and must be > 0")

    product = next((p for p in PRODUCTS if p["id"] == req.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["kind"] != "investment":
        raise HTTPException(status_code=400, detail="Product is not an investment")

    customer = await _fetch_customer(req.client_id)
    prof = investor_profile(customer)

    reasons = _suitability_check(product, prof, req.amount_rub)
    if reasons:
        return {
            "client_id": req.client_id,
            "product_id": req.product_id,
            "suitable": False,
            "reasons": reasons,
            "order": None,
            "customer_name": customer.get("name"),
        }

    symbol = INVESTMENT_SYMBOL_MAP.get(product["id"])
    order: dict = {"side": "buy", "symbol": symbol}
    note = None
    executable = False
    available_symbols: list[str] = []

    instruments = await _fetch_instruments()
    if not instruments:
        note = "backend catalogue unreachable — could not price the order"
    else:
        available_symbols = [i.get("symbol") for i in instruments if i.get("symbol")]
        match = next((i for i in instruments if i.get("symbol") == symbol), None)
        if match is None:
            # The provisional symbol guess didn't match. Surface the real
            # catalogue so the correct code is visible and the map can be fixed.
            note = (
                f"symbol '{symbol}' not found in backend catalogue — set "
                f"INVESTMENT_SYMBOL_MAP['{product['id']}'] to one of available_symbols"
            )
        else:
            price = match["price_rub"]
            qty = int(req.amount_rub // price)
            if qty < 1:
                note = f"amount {req.amount_rub} is below the price of one unit ({price})"
            else:
                order.update({
                    "qty": qty,
                    "price_rub": price,
                    "est_cost_rub": round(qty * price, 2),
                })
                executable = True

    return {
        "client_id": req.client_id,
        "product_id": req.product_id,
        "product_name": product["name"],
        "suitable": True,
        "reasons": [],
        "investor_profile": prof["profile"],
        "order": order,
        "executable": executable,
        "execute_via": f"POST {BACKEND_URL}/clients/{req.client_id}/orders",
        "note": note,
        "available_symbols": available_symbols,
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
