"""Debit card (cashback) and credit card endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services import BACKEND_URL, CIB_URL, backend_get, try_get, try_post

router = APIRouter()

# Default cashback rates by transaction type (used until CIB provides real rates)
DEFAULT_CASHBACK_RATES = {
    "card_purchase":   0.01,   # 1%
    "utility_payment": 0.005,  # 0.5%
    "atm_withdraw":    0.0,
    "transfer_out":    0.0,
    "transfer_in":     0.0,
    "salary":          0.0,
}


@router.get("/api/card-info/{client_id}")
async def card_info(client_id: str) -> dict:
    """Debit card summary with personalised cashback.

    Activates the card via CIB POST /card/activate to get segment-based
    cashback rates, then computes cashback per transaction. Falls back to
    default rates if CIB is unreachable.
    """
    customer = await backend_get(f"/clients/{client_id}")
    tx_data = await backend_get(f"/transactions/{client_id}", {"limit": "50"})
    txs = tx_data.get("items", [])

    rates = dict(DEFAULT_CASHBACK_RATES)
    rates_source = "default"
    cashback_rates_pct = {}
    segment = customer.get("segment", "mass")
    activation_message = ""

    cib = await try_post(
        CIB_URL, "/card/activate",
        {"client_id": client_id, "product_id": "card-debit-cashback"},
        timeout=5.0,
    )
    if cib:
        cashback_rates_pct = cib.get("cashback_rates_pct", {})
        activation_message = cib.get("message", "")
        segment = cib.get("segment", segment)
        rates_source = "cib"
        groceries_rate = cashback_rates_pct.get("groceries", 1.0) / 100
        transport_rate = cashback_rates_pct.get("transport", 0.5) / 100  # noqa: F841
        other_rate = cashback_rates_pct.get("other", 0.5) / 100
        rates = {
            "card_purchase":   groceries_rate,   # most card purchases = groceries
            "utility_payment": other_rate,
            "atm_withdraw":    0.0,
            "transfer_out":    0.0,
            "transfer_in":     0.0,
            "salary":          0.0,
        }

    # Real cashback balance from backend (accumulated, redeemable).
    cb_data = await try_get(BACKEND_URL, f"/cashback/{client_id}")
    cashback_balance_rub = (cb_data or {}).get(
        "cashback_balance_rub",
        customer.get("cashback_balance_rub", 0),
    )

    # Per-transaction cashback: prefer the real accrued value from backend
    # (`cashback_rub` field on each tx). Fall back to local computation only
    # for older transactions that don't carry it.
    total_cashback = 0.0
    cashback_txs = []
    for tx in txs:
        tx_type = tx.get("type", "")
        amount = abs(tx.get("amount_rub", 0))
        real_cb = tx.get("cashback_rub")
        if real_cb and real_cb > 0:
            cashback = round(real_cb, 2)
            rate = round(cashback / amount, 4) if amount else 0.0
        else:
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
        "cashback_balance_rub": cashback_balance_rub,
        "total_cashback_rub": round(total_cashback, 2),
        "cashback_transactions": cashback_txs,
        "cashback_rates_pct": cashback_rates_pct,
        "activation_message": activation_message,
        "rates": rates,
        "rates_source": rates_source,
    }


@router.post("/api/cashback-redeem")
async def cashback_redeem(payload: dict) -> dict:
    """Move accumulated cashback to the customer's main balance."""
    client_id = payload.get("client_id")
    amount = payload.get("amount_rub", 0)
    if not client_id or amount <= 0:
        raise HTTPException(status_code=400, detail="client_id and positive amount_rub required")

    backend = await try_post(BACKEND_URL, "/api/cashback/redeem",
                             {"client_id": client_id, "amount_rub": amount})
    if backend:
        return {**backend, "source": "backend"}

    raise HTTPException(status_code=502, detail="Cashback redemption is unavailable")


@router.get("/api/credit-card/{client_id}")
async def credit_card_info(client_id: str) -> dict:
    """Credit card summary: real backend data, else CIB credit-limit decision,
    else a local heuristic. Handles the secured-card fallback from CIB."""
    customer = await backend_get(f"/clients/{client_id}")

    cc = await try_get(BACKEND_URL, f"/credit-card/{client_id}")
    if cc:
        cc["source"] = "backend"
        cc["customer_name"] = customer.get("name", "")
        return cc

    eligible = False
    credit_limit = 0
    rate_pct = 24.9
    grace_days = 55
    segment = customer.get("segment", "mass")
    explanation = ""
    reasons = []
    actual_product = "card-credit"
    source = "retail-heuristic"

    cib = await try_post(
        CIB_URL, "/card/credit-limit",
        {"client_id": client_id, "product_id": "card-credit"},
        timeout=5.0,
    )
    if cib:
        eligible = cib.get("approved", False)
        credit_limit = cib.get("limit_rub", 0)
        rate_pct = cib.get("rate_pct", 24.9)
        grace_days = cib.get("grace_period_days", 55)
        segment = cib.get("segment", segment)
        reasons = cib.get("reasons", [])
        actual_product = cib.get("product_id", "card-credit")
        note = cib.get("note", "")
        explanation = note or ("; ".join(reasons) if reasons else (
            "Approved" if eligible else "Declined"))
        source = "cib"
    else:
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
            else "Not eligible: insufficient income or overdue history")

    tx_data = await backend_get(f"/transactions/{client_id}", {"limit": "20"})
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


@router.post("/api/credit-card-payment")
async def credit_card_payment(payload: dict) -> dict:
    """Make a payment toward the credit card balance."""
    client_id = payload.get("client_id")
    amount = payload.get("amount_rub", 0)
    if not client_id or amount <= 0:
        raise HTTPException(status_code=400, detail="client_id and positive amount_rub required")

    backend = await try_post(BACKEND_URL, "/credit-card-payment", payload)
    if backend:
        return backend

    return {
        "status": "ok",
        "client_id": client_id,
        "amount_rub": amount,
        "message": "Payment recorded",
        "source": "retail-simulated",
    }
