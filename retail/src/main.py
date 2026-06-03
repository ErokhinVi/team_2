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


# ---- Debit card with cashback ----

# Default cashback rates by transaction type (used until CIB provides real rates)
DEFAULT_CASHBACK_RATES = {
    "card_purchase":   0.01,   # 1%
    "utility_payment": 0.005,  # 0.5%
    "atm_withdraw":    0.0,    # no cashback
    "transfer_out":    0.0,
    "transfer_in":     0.0,
    "salary":          0.0,
}


@app.get("/api/card-info/{client_id}")
async def card_info(client_id: str) -> dict:
    """Build debit card summary with personalised cashback for a customer.

    1. Activates the card via CIB POST /card/activate (product: card-debit-cashback)
       to get personalised cashback rates based on the customer's segment.
    2. Fetches transactions from backend and calculates cashback per transaction.
    Falls back to default rates if CIB is not reachable.
    """
    # Get customer profile
    customer = await _backend_get(f"/clients/{client_id}")

    # Get transactions
    tx_data = await _backend_get(f"/transactions/{client_id}", {"limit": "50"})
    txs = tx_data.get("items", [])

    # Activate card via CIB to get personalised cashback rates
    rates = dict(DEFAULT_CASHBACK_RATES)
    rates_source = "default"
    cashback_rates_pct = {}
    segment = customer.get("segment", "mass")
    activation_message = ""

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{CIB_URL}/card/activate",
                json={"client_id": client_id, "product_id": "card-debit-cashback"},
            )
        if r.status_code == 200:
            cib = r.json()
            cashback_rates_pct = cib.get("cashback_rates_pct", {})
            activation_message = cib.get("message", "")
            segment = cib.get("segment", segment)
            rates_source = "cib"
            # Map CIB category rates to transaction types
            # CIB gives: groceries, transport, other
            groceries_rate = cashback_rates_pct.get("groceries", 1.0) / 100
            transport_rate = cashback_rates_pct.get("transport", 0.5) / 100
            other_rate = cashback_rates_pct.get("other", 0.5) / 100
            rates = {
                "card_purchase":   groceries_rate,   # most card purchases = groceries
                "utility_payment": other_rate,
                "atm_withdraw":    0.0,
                "transfer_out":    0.0,
                "transfer_in":     0.0,
                "salary":          0.0,
            }
    except httpx.HTTPError:
        pass

    # Calculate cashback per transaction
    total_cashback = 0.0
    cashback_txs = []
    for tx in txs:
        tx_type = tx.get("type", "")
        amount = abs(tx.get("amount_rub", 0))
        rate = rates.get(tx_type, 0.0)
        cashback = round(amount * rate, 2)
        if cashback > 0:
            total_cashback += cashback
            cashback_txs.append({
                "tx_id": tx.get("id"),
                "type": tx_type,
                "amount_rub": tx.get("amount_rub"),
                "cashback_rub": cashback,
                "rate": rate,
                "ts": tx.get("ts"),
                "counterparty": tx.get("counterparty", ""),
            })

    card_suffix = str(abs(hash(client_id)))[-4:]

    return {
        "client_id": client_id,
        "customer_name": customer.get("name", ""),
        "segment": segment,
        "card_number_masked": f"**** **** **** {card_suffix}",
        "balance_rub": customer.get("balance_rub", 0),
        "total_cashback_rub": round(total_cashback, 2),
        "cashback_transactions": cashback_txs,
        "cashback_rates_pct": cashback_rates_pct,
        "activation_message": activation_message,
        "rates": rates,
        "rates_source": rates_source,
    }


# ---- Credit card ----

@app.get("/api/credit-card/{client_id}")
async def credit_card_info(client_id: str) -> dict:
    """Credit card summary for a customer.

    1. Tries backend GET /credit-card/{client_id} for real credit card data.
    2. If not available, asks CIB POST /card/credit-limit for a personalised
       credit limit decision (based on income, segment, risk score).
    3. Falls back to local heuristic if CIB is also unreachable.
    """
    customer = await _backend_get(f"/clients/{client_id}")

    # Try real credit card data from backend
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{BACKEND_URL}/credit-card/{client_id}")
        if r.status_code == 200:
            cc = r.json()
            cc["source"] = "backend"
            cc["customer_name"] = customer.get("name", "")
            return cc
    except httpx.HTTPError:
        pass

    # Ask CIB for credit card limit decision
    eligible = False
    credit_limit = 0
    rate_pct = 24.9
    grace_days = 55
    segment = customer.get("segment", "mass")
    explanation = ""
    reasons = []
    actual_product = "card-credit"
    source = "retail-heuristic"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{CIB_URL}/card/credit-limit",
                json={"client_id": client_id, "product_id": "card-credit"},
            )
        if r.status_code == 200:
            cib = r.json()
            eligible = cib.get("approved", False)
            credit_limit = cib.get("limit_rub", 0)
            rate_pct = cib.get("rate_pct", 24.9)
            grace_days = cib.get("grace_period_days", 55)
            segment = cib.get("segment", segment)
            reasons = cib.get("reasons", [])
            # CIB may offer a secured card for borderline customers
            actual_product = cib.get("product_id", "card-credit")
            note = cib.get("note", "")
            explanation = note or ("; ".join(reasons) if reasons else (
                "Approved" if eligible else "Declined"
            ))
            source = "cib"
    except httpx.HTTPError:
        # CIB unreachable — local heuristic
        income = customer.get("income_rub", 0)
        has_overdue = customer.get("has_overdue_history", False)
        eligible = income >= 25_000 and not has_overdue
        if eligible:
            if income >= 150_000:
                credit_limit = 500_000
            elif income >= 80_000:
                credit_limit = 300_000
            elif income >= 50_000:
                credit_limit = 150_000
            else:
                credit_limit = 75_000
        explanation = (
            "Approved based on income and history" if eligible
            else "Not eligible: insufficient income or overdue history"
        )

    # Simulate some usage based on existing transactions
    tx_data = await _backend_get(f"/transactions/{client_id}", {"limit": "20"})
    txs = tx_data.get("items", [])
    card_purchases = [tx for tx in txs if tx.get("type") == "card_purchase"]
    total_spent = sum(abs(tx.get("amount_rub", 0)) for tx in card_purchases[:5])
    balance_owed = min(total_spent, int(credit_limit * 0.4)) if credit_limit else 0
    available = credit_limit - balance_owed
    min_payment = max(int(balance_owed * 0.05), 1000) if balance_owed > 0 else 0

    card_suffix = str(abs(hash(client_id + "cc")))[-4:]

    product_id = actual_product if source == "cib" else "card-credit"
    is_secured = product_id == "card-credit-secured"

    return {
        "client_id": client_id,
        "customer_name": customer.get("name", ""),
        "segment": segment,
        "eligible": eligible,
        "explanation": explanation,
        "reasons": reasons,
        "product_id": product_id,
        "is_secured": is_secured,
        "card_number_masked": f"**** **** **** {card_suffix}",
        "credit_limit_rub": credit_limit,
        "balance_owed_rub": balance_owed,
        "available_rub": available,
        "min_payment_rub": min_payment,
        "interest_rate_pct": rate_pct,
        "grace_period_days": grace_days,
        "source": source,
    }


@app.post("/api/credit-card-payment")
async def credit_card_payment(payload: dict) -> dict:
    """Make a payment toward the credit card balance.

    Tries backend POST /credit-card-payment. If not available, returns
    a simulated confirmation.
    """
    client_id = payload.get("client_id")
    amount = payload.get("amount_rub", 0)

    if not client_id or amount <= 0:
        raise HTTPException(status_code=400, detail="client_id and positive amount_rub required")

    # Try real endpoint on backend
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{BACKEND_URL}/credit-card-payment", json=payload)
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        pass

    # Fallback: simulated payment confirmation
    return {
        "status": "ok",
        "client_id": client_id,
        "amount_rub": amount,
        "message": "Payment recorded",
        "source": "retail-simulated",
    }


# ---- Savings / Deposits ----

@app.get("/api/deposits/{client_id}")
async def deposits_info(client_id: str) -> dict:
    """Savings account overview for a customer.

    1. Fetches deposit products from CIB (GET /products, kind=deposit).
    2. Tries backend GET /deposits/{client_id} for real deposit data.
    3. If backend doesn't have that yet, returns product catalogue only
       so the UI can show available deposit offers.
    """
    customer = await _backend_get(f"/clients/{client_id}")

    # Get deposit products from CIB
    deposit_products = []
    try:
        products = await _cib_get("/products")
        deposit_products = [
            p for p in (products.get("items") or [])
            if p.get("kind") in ("deposit", "savings")
        ]
    except Exception:
        pass

    # Try real deposits from backend
    existing_deposits = []
    total_deposited = 0
    total_interest = 0
    deposits_source = "none"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{BACKEND_URL}/deposits/{client_id}")
        if r.status_code == 200:
            dep_data = r.json()
            existing_deposits = dep_data.get("items", [])
            total_deposited = sum(d.get("amount_rub", 0) for d in existing_deposits)
            total_interest = sum(d.get("interest_earned_rub", 0) for d in existing_deposits)
            deposits_source = "backend"
    except httpx.HTTPError:
        pass

    return {
        "client_id": client_id,
        "customer_name": customer.get("name", ""),
        "balance_rub": customer.get("balance_rub", 0),
        "deposit_products": deposit_products,
        "existing_deposits": existing_deposits,
        "total_deposited_rub": total_deposited,
        "total_interest_rub": total_interest,
        "deposits_source": deposits_source,
    }


@app.post("/api/deposit-open")
async def deposit_open(payload: dict) -> dict:
    """Open a new deposit / savings account.

    1. Tries CIB POST /deposit/open (returns confirmation with rate,
       maturity date, projected interest).
    2. Falls back to backend POST /deposits.
    3. Falls back to simulated confirmation.
    """
    client_id = payload.get("client_id")
    product_id = payload.get("product_id")
    amount = payload.get("amount_rub", 0)
    term_months = payload.get("term_months", 12)

    if not client_id or not product_id or amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, product_id and positive amount_rub required",
        )

    # Try CIB deposit/open endpoint (has rate, maturity, projected interest)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{CIB_URL}/deposit/open",
                json={
                    "client_id": client_id,
                    "product_id": product_id,
                    "amount_rub": amount,
                },
            )
        if r.status_code == 200:
            cib = r.json()
            return {
                "status": "ok",
                "opened": cib.get("opened", True),
                "client_id": cib.get("client_id", client_id),
                "product_id": cib.get("product_id", product_id),
                "product_name": cib.get("product_name", ""),
                "amount_rub": cib.get("amount_rub", amount),
                "rate_pct": cib.get("rate_pct", 0),
                "term_months": cib.get("term_months"),
                "early_withdrawal": cib.get("early_withdrawal", False),
                "opened_at": cib.get("opened_at", ""),
                "matures_at": cib.get("matures_at"),
                "estimated_interest_rub": cib.get("projected_interest_rub", 0),
                "customer_name": cib.get("customer_name", ""),
                "source": "cib",
            }
    except httpx.HTTPError:
        pass

    # Try backend
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{BACKEND_URL}/deposits", json=payload)
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        pass

    # Fallback: simulated deposit opening
    rate_pct = 14.0
    try:
        products = await _cib_get("/products")
        for p in products.get("items", []):
            if p.get("id") == product_id and p.get("rate_pct"):
                rate_pct = p["rate_pct"]
                break
    except Exception:
        pass

    estimated_interest = round(amount * (rate_pct / 100) * (term_months / 12), 2)

    return {
        "status": "ok",
        "client_id": client_id,
        "product_id": product_id,
        "amount_rub": amount,
        "term_months": term_months,
        "rate_pct": rate_pct,
        "estimated_interest_rub": estimated_interest,
        "message": "Deposit opened successfully",
        "source": "retail-simulated",
    }
