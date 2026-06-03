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
    {"id": "mortgage", "kind": "mortgage", "name": "Ипотека", "rate_pct": 16.0,
     "term_years_max": 30, "min_down_payment_pct": 20, "max_ltv_pct": 80},
    # Investment / tradable securities. risk_level 1 (lowest) .. 5 (highest).
    # cib owns the trading TERMS (lot_size, commission_pct, min_order_rub,
    # suitability); `ticker` matches backend's live catalogue (GET /instruments),
    # since backend executes orders by that exact code. `alt_tickers` lists other
    # acceptable codes for the same product (e.g. blue-chip basket).
    {"id": "inv-ofz",        "kind": "investment", "subtype": "bond",  "ticker": "OFZ26", "asset_type": "bond",        "name": "Гособлигации (ОФЗ)",            "risk_level": 1, "expected_return_pct": 13.0, "lot_size": 1,  "commission_pct": 0.10, "min_order_rub": 10_000, "min_investment_rub": 10_000},
    {"id": "inv-corp-bond",  "kind": "investment", "subtype": "bond",  "ticker": "FXCB",  "asset_type": "bond_fund",   "name": "Фонд корпоративных облигаций",  "risk_level": 2, "expected_return_pct": 16.0, "lot_size": 1,  "commission_pct": 0.15, "min_order_rub": 10_000, "min_investment_rub": 10_000},
    {"id": "inv-etf-index",  "kind": "investment", "subtype": "etf",   "ticker": "FXIM",  "asset_type": "etf",         "name": "ETF на индекс Мосбиржи",        "risk_level": 3, "expected_return_pct": 18.0, "lot_size": 1,  "commission_pct": 0.20, "min_order_rub": 5_000,  "min_investment_rub": 5_000},
    {"id": "inv-equity-fund","kind": "investment", "subtype": "fund",  "ticker": "FXEQ",  "asset_type": "equity_fund", "name": "Фонд акций",                    "risk_level": 3, "expected_return_pct": 19.0, "lot_size": 1,  "commission_pct": 0.20, "min_order_rub": 5_000,  "min_investment_rub": 5_000},
    {"id": "inv-bluechip",   "kind": "investment", "subtype": "stock", "ticker": "SBER",  "asset_type": "stock",       "name": "Голубые фишки (акции)",         "risk_level": 4, "expected_return_pct": 22.0, "lot_size": 1,  "commission_pct": 0.30, "min_order_rub": 30_000, "min_investment_rub": 30_000, "alt_tickers": ["GAZP", "LKOH"]},
    {"id": "inv-growth",     "kind": "investment", "subtype": "stock", "ticker": "YNDX",  "asset_type": "stock",       "name": "Акции роста",                   "risk_level": 5, "expected_return_pct": 28.0, "lot_size": 1,  "commission_pct": 0.30, "min_order_rub": 50_000, "min_investment_rub": 50_000},
]

# Human-readable investor risk profile names by max acceptable risk level.
RISK_LEVEL_NAMES = {
    1: "conservative",
    2: "cautious",
    3: "balanced",
    4: "growth",
    5: "aggressive",
}

# Minimum commission the bank charges on any trade, regardless of size.
MIN_COMMISSION_RUB = 50.0

# Routes backend's next-best-offer product codes to the matching cib product
# and the call the app should make to act on the offer. Codes cib can't fulfil
# yet (mortgage) or that belong to backend (premium_upgrade, cashback_redeem)
# are passed through with a marker so the app still knows how to handle them.
OFFER_ROUTING: dict[str, dict] = {
    "deposit-12m":     {"cib_product": "deposit-12m",     "action": ("POST", "/deposit/open")},
    "deposit-flex":    {"cib_product": "deposit-flex",    "action": ("POST", "/deposit/open")},
    "credit_card":     {"cib_product": "card-credit",     "action": ("POST", "/card/credit-limit")},
    "consumer_credit": {"cib_product": "credit-consumer", "action": ("POST", "/credit/decide")},
    "investments":     {"cib_product": None,              "action": ("POST", "/investment/recommend")},
    "mortgage":        {"cib_product": "mortgage",        "action": ("POST", "/mortgage/decide")},
    "premium_upgrade": {"cib_product": None, "action": None, "handled_by": "backend",
                        "note": "segment upgrade — handled by backend/retail"},
    "cashback_redeem": {"cib_product": None, "action": ("POST", "/api/cashback/redeem"),
                        "handled_by": "backend"},
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

# Mortgage thresholds
MORTGAGE_MAX_RISK = 0.55
MORTGAGE_MIN_INCOME = 40_000     # mortgages need a stronger income
MORTGAGE_MAX_DTI = 0.50          # monthly payment <= 50% of monthly income

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


class MortgageRequest(BaseModel):
    client_id: str
    property_price_rub: float
    down_payment_rub: float
    term_years: int = 20


class OrderCheckRequest(BaseModel):
    client_id: str
    product_id: str
    side: str = "buy"          # "buy" or "sell"
    qty: int
    price_rub: float | None = None  # if omitted, priced from backend catalogue


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


@app.post("/mortgage/decide")
async def mortgage_decide(req: MortgageRequest) -> dict:
    product = next((p for p in PRODUCTS if p["id"] == "mortgage"), None)
    if product is None:
        raise HTTPException(status_code=500, detail="Mortgage product missing")

    if req.property_price_rub <= 0 or req.down_payment_rub < 0:
        raise HTTPException(status_code=400, detail="Invalid property price or down payment")
    if req.down_payment_rub >= req.property_price_rub:
        raise HTTPException(status_code=400, detail="Down payment cannot cover the whole property")

    customer = await _fetch_customer(req.client_id)
    income = customer.get("income_rub", 0)
    risk = customer.get("risk_score", 1.0)

    loan_rub = req.property_price_rub - req.down_payment_rub
    down_pct = req.down_payment_rub / req.property_price_rub * 100
    ltv_pct = loan_rub / req.property_price_rub * 100

    # Monthly annuity payment
    term_years = max(1, min(req.term_years, product["term_years_max"]))
    n = term_years * 12
    r = product["rate_pct"] / 100 / 12
    monthly_payment = round(loan_rub * r / (1 - (1 + r) ** -n)) if r > 0 else round(loan_rub / n)

    reasons: list[str] = []
    if down_pct < product["min_down_payment_pct"]:
        reasons.append(
            f"down payment below minimum ({down_pct:.0f}% < {product['min_down_payment_pct']}%)"
        )
    if customer.get("has_overdue_history"):
        reasons.append("overdue payment history")
    if risk > MORTGAGE_MAX_RISK:
        reasons.append(f"risk score too high ({risk:.2f})")
    if income < MORTGAGE_MIN_INCOME:
        reasons.append(f"income below minimum ({income} < {MORTGAGE_MIN_INCOME})")
    if income > 0 and monthly_payment > income * MORTGAGE_MAX_DTI:
        reasons.append(
            f"monthly payment {monthly_payment} exceeds {int(MORTGAGE_MAX_DTI*100)}% of income ({income})"
        )

    approved = not reasons

    # On approval, record the mortgage on the customer's profile so it sticks
    # and counts. Best-effort — a transient backend hiccup won't block the decision.
    recorded = False
    if approved:
        recorded = await _record_product(req.client_id, "mortgage", {
            "loan_amount_rub": round(loan_rub, 2),
            "rate_pct": product["rate_pct"],
            "term_years": term_years,
            "monthly_payment_rub": monthly_payment,
        })

    explanation = ""
    try:
        verdict = "approved" if approved else "declined"
        prompt = (
            f"A customer applied for a mortgage of {loan_rub:.0f} rubles over {term_years} years. "
            f"Decision: {verdict}. Reasons: {', '.join(reasons) if reasons else 'all checks passed'}. "
            "Write a short, polite one-sentence explanation for the customer in English."
        )
        explanation = await ask_llm(prompt)
    except LLMError:
        explanation = ("Your mortgage application has been approved." if approved
                       else "We are unable to approve this mortgage at this time.")

    return {
        "client_id": req.client_id,
        "product_id": "mortgage",
        "approved": approved,
        "recorded": recorded,
        "property_price_rub": req.property_price_rub,
        "down_payment_rub": req.down_payment_rub,
        "loan_amount_rub": round(loan_rub, 2),
        "down_payment_pct": round(down_pct, 1),
        "ltv_pct": round(ltv_pct, 1),
        "rate_pct": product["rate_pct"],
        "term_years": term_years,
        "monthly_payment_rub": monthly_payment,
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


def _product_terms(p: dict) -> dict:
    """Customer-facing terms of a product, for showing inside an offer."""
    keys = ("rate_pct", "term_months", "grace_period_days", "expected_return_pct",
            "risk_level", "commission_pct", "cashback_categories", "early_withdrawal",
            "min_investment_rub")
    return {k: p[k] for k in keys if k in p}


@app.get("/clients/{client_id}/next-best-offers")
async def next_best_offers(client_id: str, limit: int = 5) -> dict:
    """Turn backend's analytical recommendations into ready-to-act offers:
    each suggestion is enriched with cib's real product terms and the exact
    call the app should make to act on it."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/clients/{client_id}/recommendations",
                params={"limit": limit},
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Backend recommendations unavailable")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Client not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Backend recommendations unavailable")
    data = resp.json()

    offers = []
    for rec in data.get("recommendations", []):
        code = rec.get("product")
        routing = OFFER_ROUTING.get(code)
        cib: dict = {"available": False}
        if routing is None:
            cib["note"] = "unknown product code"
        else:
            cib_product = routing.get("cib_product")
            if cib_product:
                prod = next((p for p in PRODUCTS if p["id"] == cib_product), None)
                if prod:
                    cib.update({
                        "available": True,
                        "product_id": cib_product,
                        "name": prod["name"],
                        "kind": prod["kind"],
                        "terms": _product_terms(prod),
                    })
            action = routing.get("action")
            if action:
                cib["action"] = {"method": action[0], "path": action[1]}
            if routing.get("handled_by"):
                cib["handled_by"] = routing["handled_by"]
            if routing.get("note"):
                cib["note"] = routing["note"]
        offers.append({**rec, "cib": cib})

    return {
        "client_id": client_id,
        "name": data.get("name"),
        "segment": data.get("segment"),
        "total": len(offers),
        "offers": offers,
    }


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

    symbol = product["ticker"]
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
            # cib's ticker isn't in backend's catalogue yet. Surface the real
            # catalogue so backend can align to cib's canonical ticker.
            note = (
                f"ticker '{symbol}' not found in backend catalogue — backend should "
                f"trade product '{product['id']}' under this ticker (see available_symbols)"
            )
        else:
            price = match["price_rub"]
            lot = product["lot_size"]
            comm_pct = product["commission_pct"]
            # Largest whole number of lots whose value + commission fits the amount.
            qty = (int(req.amount_rub // price) // lot) * lot
            while qty >= lot:
                gross = qty * price
                comm = max(gross * comm_pct / 100, MIN_COMMISSION_RUB)
                if gross + comm <= req.amount_rub:
                    break
                qty -= lot
            if qty < lot:
                note = f"amount {req.amount_rub} is too small to cover one lot ({lot}) plus commission"
            else:
                gross = round(qty * price, 2)
                comm = round(max(gross * comm_pct / 100, MIN_COMMISSION_RUB), 2)
                order.update({
                    "qty": qty,
                    "price_rub": price,
                    "gross_rub": gross,
                    "commission_rub": comm,
                    "total_cost_rub": round(gross + comm, 2),
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


@app.get("/securities")
async def securities() -> dict:
    """Tradable securities with their trading terms. cib is the source of truth
    for ticker, asset type, lot size, commission and minimum order."""
    items = [
        {"id": p["id"], "ticker": p["ticker"], "asset_type": p["asset_type"],
         "name": p["name"], "risk_level": p["risk_level"],
         "expected_return_pct": p["expected_return_pct"], "lot_size": p["lot_size"],
         "commission_pct": p["commission_pct"], "min_order_rub": p["min_order_rub"]}
        for p in PRODUCTS if p["kind"] == "investment"
    ]
    return {"total": len(items), "items": items}


@app.post("/investment/order-check")
async def investment_order_check(req: OrderCheckRequest) -> dict:
    """Validate a proposed trade and return the commission the bank charges.

    Enforces cib's trading rules: valid side, positive whole lots, minimum order
    size, suitability (buy), and — for a buy — that the customer holds enough
    cash to cover trade value plus commission. Backend still executes and is the
    authority on share ownership for sells.
    """
    side = req.side.lower()
    if side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="side must be 'buy' or 'sell'")

    product = next((p for p in PRODUCTS if p["id"] == req.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["kind"] != "investment":
        raise HTTPException(status_code=400, detail="Product is not a tradable security")

    customer = await _fetch_customer(req.client_id)

    reasons: list[str] = []

    # Quantity / lot rules
    lot = product["lot_size"]
    if req.qty <= 0:
        reasons.append("quantity must be greater than zero")
    elif req.qty % lot != 0:
        reasons.append(f"quantity must be a whole multiple of the lot size ({lot})")

    # Price: from the request, else from backend's live catalogue
    price = req.price_rub
    if price is None:
        instruments = await _fetch_instruments()
        match = next((i for i in instruments if i.get("symbol") == product["ticker"]), None)
        if match is not None:
            price = match["price_rub"]
    if price is None:
        reasons.append("could not determine a price (pass price_rub or ensure backend prices the ticker)")

    gross_rub = round(price * req.qty, 2) if price is not None else None
    commission_rub = None
    total_cost_rub = None
    net_proceeds_rub = None

    if gross_rub is not None:
        commission_rub = round(max(gross_rub * product["commission_pct"] / 100, MIN_COMMISSION_RUB), 2)

        # Minimum order size (applies to buys)
        if side == "buy" and gross_rub < product["min_order_rub"]:
            reasons.append(f"order value below minimum ({gross_rub} < {product['min_order_rub']})")

        if side == "buy":
            total_cost_rub = round(gross_rub + commission_rub, 2)
            # Suitability — only gate buys
            prof = investor_profile(customer)
            reasons.extend(_suitability_check(product, prof, gross_rub))
            # Cash check: must cover trade value plus commission
            if customer.get("balance_rub", 0) < total_cost_rub:
                reasons.append(
                    f"insufficient cash ({customer.get('balance_rub', 0)} < {total_cost_rub} incl. commission)"
                )
        else:  # sell
            net_proceeds_rub = round(gross_rub - commission_rub, 2)

    valid = not reasons

    return {
        "client_id": req.client_id,
        "product_id": req.product_id,
        "ticker": product["ticker"],
        "asset_type": product["asset_type"],
        "side": side,
        "qty": req.qty,
        "price_rub": price,
        "gross_rub": gross_rub,
        "commission_pct": product["commission_pct"],
        "commission_rub": commission_rub,
        "total_cost_rub": total_cost_rub,      # buy: cash needed (gross + commission)
        "net_proceeds_rub": net_proceeds_rub,  # sell: cash received (gross - commission)
        "valid": valid,
        "reasons": reasons,
        "customer_name": customer.get("name"),
    }


# English subtitles + one-line benefit per product, for the customer showcase.
PRODUCT_COPY = {
    "card-debit-cashback": ("Cashback debit card", "Up to 7% back on everyday spending"),
    "card-credit":         ("Credit card", "55 days interest-free"),
    "card-credit-secured": ("Secured credit card", "Build your limit, get approved"),
    "deposit-3m":          ("3-month deposit", "Short term, guaranteed return"),
    "deposit-6m":          ("6-month deposit", "Balanced term and rate"),
    "deposit-12m":         ("12-month deposit", "Our best savings rate"),
    "deposit-flex":        ("Flexible savings", "Withdraw anytime, earn daily"),
    "credit-consumer":     ("Consumer loan", "Instant decision, fair rate"),
    "mortgage":            ("Mortgage", "Your own home, from 16%"),
    "inv-ofz":             ("Government bonds", "Lowest risk, steady income"),
    "inv-corp-bond":       ("Corporate bond fund", "Higher yield, low risk"),
    "inv-etf-index":       ("Index ETF", "The whole market in one buy"),
    "inv-equity-fund":     ("Equity fund", "Diversified growth"),
    "inv-bluechip":        ("Blue-chip stocks", "Russia's strongest names"),
    "inv-growth":          ("Growth stocks", "Higher risk, higher upside"),
}

# Category metadata: kind -> (section title, icon, accent)
CATEGORIES = [
    ("Cards", "💳", ("card", "credit_card")),
    ("Savings & Deposits", "🏦", ("deposit",)),
    ("Lending", "💰", ("credit", "mortgage")),
    ("Investments", "📈", ("investment",)),
]


def _product_highlight(p: dict) -> str:
    """A short, customer-facing headline figure for a product card."""
    kind = p["kind"]
    if kind == "card":
        return "Cashback up to 7%"
    if kind == "credit_card":
        return f"{p['rate_pct']}% · {p['grace_period_days']}-day grace"
    if kind == "deposit":
        term = f"{p['term_months']} mo" if p.get("term_months") else "flexible"
        return f"{p['rate_pct']}% p.a. · {term}"
    if kind == "credit":
        return f"from {p['rate_pct']}%"
    if kind == "mortgage":
        return f"from {p['rate_pct']}% · up to {p['term_years_max']} yrs"
    if kind == "investment":
        return f"~{p['expected_return_pct']}% · risk {p['risk_level']}/5"
    return ""


def _preapprove_consumer_loan(c: dict) -> dict | None:
    """Largest consumer loan the customer is already approved for, or None."""
    income = c.get("income_rub", 0)
    risk = c.get("risk_score", 1.0)
    if c.get("has_overdue_history") or income < MIN_INCOME_RUB or risk > MAX_RISK_SCORE_STANDARD:
        return None
    amount = min(round(income * 12 * (1.0 - risk) / 10_000) * 10_000, 3_000_000)
    if amount < 30_000:
        return None
    prod = next(p for p in PRODUCTS if p["id"] == "credit-consumer")
    return {
        "product_id": "credit-consumer", "type": "loan", "name": prod["name"],
        "headline": f"You're pre-approved for a loan up to {amount:,} ₽".replace(",", " "),
        "amount_rub": amount, "rate_pct": prod["rate_pct"],
        "action": {"method": "POST", "path": "/credit/decide"},
    }


def _preapprove_credit_card(c: dict) -> dict | None:
    """Credit card limit the customer is already approved for, or None.
    Mirrors the logic of POST /card/credit-limit."""
    income = c.get("income_rub", 0)
    risk = c.get("risk_score", 1.0)
    segment = c.get("segment", "mass")
    if c.get("has_overdue_history"):
        return None
    standard = risk <= CREDIT_CARD_MAX_RISK and income >= CREDIT_CARD_MIN_INCOME
    secured = (not standard) and risk <= SECURED_CARD_MAX_RISK and income >= SECURED_CARD_MIN_INCOME
    if not standard and not secured:
        return None
    if standard:
        mult = CREDIT_CARD_LIMIT_MULTIPLIER.get(segment, 2.0)
        limit = round(income * mult * (1.0 - risk) / 10_000) * 10_000
        pid = "card-credit"
    else:
        limit = min(round(income * 0.5 / 5_000) * 5_000, SECURED_CARD_MAX_LIMIT)
        pid = "card-credit-secured"
    if limit < 10_000:
        return None
    prod = next(p for p in PRODUCTS if p["id"] == pid)
    return {
        "product_id": pid, "type": "credit_card", "name": prod["name"],
        "headline": f"A credit card with a {limit:,} ₽ limit is ready for you".replace(",", " "),
        "limit_rub": limit, "rate_pct": prod["rate_pct"],
        "grace_period_days": prod["grace_period_days"],
        "action": {"method": "POST", "path": "/card/credit-limit"},
    }


def _prequalify_mortgage(c: dict) -> dict | None:
    """Maximum mortgage the customer pre-qualifies for (20-yr term), or None."""
    income = c.get("income_rub", 0)
    risk = c.get("risk_score", 1.0)
    if c.get("has_overdue_history") or income < MORTGAGE_MIN_INCOME or risk > MORTGAGE_MAX_RISK:
        return None
    prod = next(p for p in PRODUCTS if p["id"] == "mortgage")
    term_years = 20
    n = term_years * 12
    r = prod["rate_pct"] / 100 / 12
    max_payment = income * MORTGAGE_MAX_DTI
    max_loan = round(max_payment * (1 - (1 + r) ** -n) / r / 100_000) * 100_000
    if max_loan < 500_000:
        return None
    return {
        "product_id": "mortgage", "type": "mortgage", "name": prod["name"],
        "headline": f"Pre-qualified for a mortgage up to {max_loan:,} ₽".replace(",", " "),
        "max_loan_rub": max_loan, "rate_pct": prod["rate_pct"], "term_years": term_years,
        "action": {"method": "POST", "path": "/mortgage/decide"},
    }


@app.get("/clients/{client_id}/pre-approved")
async def pre_approved(client_id: str) -> dict:
    """Pre-approved offers: runs cib's decision logic proactively so the app can
    show 'you're already approved for X' instead of making the customer apply.
    Skips products the customer already holds."""
    customer = await _fetch_customer(client_id)
    held = set(customer.get("products", []))

    offers = []
    if "consumer_credit" not in held:
        o = _preapprove_consumer_loan(customer)
        if o:
            offers.append(o)
    if "credit_card" not in held:
        o = _preapprove_credit_card(customer)
        if o:
            offers.append(o)
    if "mortgage" not in held:
        o = _prequalify_mortgage(customer)
        if o:
            offers.append(o)

    return {
        "client_id": client_id,
        "customer_name": customer.get("name"),
        "total": len(offers),
        "offers": offers,
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    def card(p: dict) -> str:
        en, benefit = PRODUCT_COPY.get(p["id"], (p["name"], ""))
        return (
            "<article class='card'>"
            f"<div class='hl'>{_product_highlight(p)}</div>"
            f"<h3>{en}</h3>"
            f"<div class='ru'>{p['name']}</div>"
            f"<p>{benefit}</p>"
            "</article>"
        )

    sections = ""
    for title, icon, kinds in CATEGORIES:
        items = [p for p in PRODUCTS if p["kind"] in kinds]
        if not items:
            continue
        cards = "".join(card(p) for p in items)
        sections += (
            f"<section><h2><span class='ic'>{icon}</span>{title}"
            f"<span class='count'>{len(items)}</span></h2>"
            f"<div class='grid'>{cards}</div></section>"
        )

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Raiffeisen — Products</title><style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:-apple-system,Segoe UI,Roboto,system-ui,sans-serif;"
        "background:#f5f6f8;color:#1a1a1a;line-height:1.5}"
        ".hero{background:#ffed00;padding:40px 24px 48px}"
        ".hero .wrap{max-width:1040px;margin:0 auto}"
        ".brand{font-weight:800;font-size:15px;letter-spacing:.5px;color:#111}"
        ".hero h1{font-size:34px;font-weight:800;margin:14px 0 8px;max-width:620px}"
        ".hero p{font-size:17px;color:#3a3a26;max-width:560px}"
        ".stats{display:flex;gap:28px;flex-wrap:wrap;margin-top:24px}"
        ".stat b{display:block;font-size:24px;font-weight:800}"
        ".stat span{font-size:13px;color:#4a4a30}"
        ".main{max-width:1040px;margin:-24px auto 56px;padding:0 24px}"
        "section{margin-top:36px}"
        "h2{font-size:20px;font-weight:700;display:flex;align-items:center;gap:10px;margin-bottom:14px}"
        ".ic{font-size:22px}"
        ".count{font-size:12px;font-weight:700;background:#111;color:#ffed00;"
        "border-radius:20px;padding:2px 9px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:14px}"
        ".card{background:#fff;border:1px solid #ececec;border-radius:14px;padding:18px;"
        "transition:transform .12s ease,box-shadow .12s ease}"
        ".card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,.08)}"
        ".hl{display:inline-block;font-size:13px;font-weight:700;color:#111;"
        "background:#ffed00;border-radius:8px;padding:3px 9px;margin-bottom:10px}"
        ".card h3{font-size:16px;font-weight:700}"
        ".card .ru{font-size:12px;color:#999;margin:2px 0 8px}"
        ".card p{font-size:13px;color:#555}"
        "footer{max-width:1040px;margin:0 auto 40px;padding:0 24px;font-size:12px;color:#aaa}"
        "</style></head><body>"
        "<div class='hero'><div class='wrap'>"
        "<div class='brand'>RAIFFEISEN</div>"
        "<h1>Smart banking products, instant decisions</h1>"
        "<p>Every loan, card and investment is checked for you in real time — "
        "approved fast, priced fairly, suited to you.</p>"
        "<div class='stats'>"
        f"<div class='stat'><b>{len(PRODUCTS)}</b><span>products</span></div>"
        "<div class='stat'><b>instant</b><span>credit decisions</span></div>"
        "<div class='stat'><b>risk-checked</b><span>investments</span></div>"
        "<div class='stat'><b>0%</b><span>hidden fees</span></div>"
        "</div></div></div>"
        f"<div class='main'>{sections}</div>"
        f"<footer>Team {TEAM_NAME} · corporate &amp; business logic · live catalogue</footer>"
        "</body></html>"
    )
