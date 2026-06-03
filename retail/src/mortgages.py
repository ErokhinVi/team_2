"""Mortgage endpoints: live quote + application.

Wires through:
  * CIB POST /mortgage/quote   — decision + monthly payment + LTV + DTI (when shipped)
  * CIB POST /mortgage/apply   — commit (when shipped)
  * Backend POST /clients/{id}/mortgages — store the opened mortgage (when shipped)

Falls back to a transparent local annuity calculation so the screen is usable
end-to-end immediately. The fallback rules — 20% min down payment,
40% max DTI, 14.5% default rate — mirror typical RU mortgage policy.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services import BACKEND_URL, CIB_URL, backend_get, try_get, try_post

router = APIRouter()

# Fallback policy used until CIB ships a mortgage decision endpoint
DEFAULT_RATE_PCT = 14.5
MIN_DOWN_PAYMENT_PCT = 20.0
MAX_DTI_PCT = 40.0
MIN_TERM_YEARS = 5
MAX_TERM_YEARS = 30
MIN_LOAN_RUB = 500_000


def _monthly_payment(principal: float, annual_rate_pct: float, term_months: int) -> float:
    """Standard annuity formula."""
    if term_months <= 0 or principal <= 0:
        return 0.0
    r = (annual_rate_pct / 100.0) / 12.0
    if r == 0:
        return round(principal / term_months, 2)
    factor = (1 + r) ** term_months
    return round(principal * (r * factor) / (factor - 1), 2)


def _local_quote(customer: dict, property_price: float, down_payment: float,
                 term_years: int, rate_pct: float | None = None) -> dict:
    """Fallback decision when CIB doesn't have a mortgage endpoint yet."""
    rate = rate_pct if rate_pct is not None else DEFAULT_RATE_PCT
    loan = round(property_price - down_payment, 2)
    term_months = term_years * 12
    monthly = _monthly_payment(loan, rate, term_months)
    total_to_pay = round(monthly * term_months, 2)
    total_interest = round(total_to_pay - loan, 2)
    ltv_pct = round((loan / property_price) * 100, 2) if property_price > 0 else 0
    income = customer.get("income_rub", 0) or 0
    dti_pct = round((monthly / income) * 100, 2) if income > 0 else None
    has_overdue = customer.get("has_overdue_history", False)

    reasons = []
    if loan < MIN_LOAN_RUB:
        reasons.append(f"loan below minimum ({loan} < {MIN_LOAN_RUB})")
    if term_years < MIN_TERM_YEARS or term_years > MAX_TERM_YEARS:
        reasons.append(f"term must be between {MIN_TERM_YEARS} and {MAX_TERM_YEARS} years")
    if down_payment <= 0 or (down_payment / property_price * 100) < MIN_DOWN_PAYMENT_PCT:
        reasons.append(f"down payment below {MIN_DOWN_PAYMENT_PCT}% of property price")
    if dti_pct is not None and dti_pct > MAX_DTI_PCT:
        reasons.append(f"DTI {dti_pct}% exceeds maximum {MAX_DTI_PCT}%")
    if has_overdue:
        reasons.append("overdue payment history")

    approved = not reasons
    return {
        "approved": approved,
        "rate_pct": rate,
        "loan_amount_rub": loan,
        "monthly_payment_rub": monthly,
        "total_to_pay_rub": total_to_pay,
        "total_interest_rub": total_interest,
        "ltv_pct": ltv_pct,
        "dti_pct": dti_pct,
        "term_years": term_years,
        "term_months": term_months,
        "reasons": reasons,
        "source": "retail-heuristic",
    }


@router.get("/api/mortgage/{client_id}")
async def mortgage_info(client_id: str) -> dict:
    """Mortgage screen overview: customer profile + any existing mortgages."""
    customer = await backend_get(f"/clients/{client_id}")

    # Try to read existing mortgages from backend (optional)
    existing = []
    mortgages_source = "none"
    data = await try_get(BACKEND_URL, f"/clients/{client_id}/mortgages")
    if data and isinstance(data, dict):
        existing = data.get("items", [])
        mortgages_source = "backend"

    # Pull the bank's mortgage product (rate etc.) from CIB catalogue if present
    rate_pct = DEFAULT_RATE_PCT
    products = await try_get(CIB_URL, "/products") or {}
    for p in products.get("items", []):
        if p.get("kind") == "mortgage" or str(p.get("id", "")).startswith("mortgage"):
            if p.get("rate_pct"):
                rate_pct = p["rate_pct"]
                break

    return {
        "client_id": client_id,
        "customer_name": customer.get("name", ""),
        "income_rub": customer.get("income_rub", 0),
        "balance_rub": customer.get("balance_rub", 0),
        "default_rate_pct": rate_pct,
        "min_down_payment_pct": MIN_DOWN_PAYMENT_PCT,
        "max_dti_pct": MAX_DTI_PCT,
        "min_term_years": MIN_TERM_YEARS,
        "max_term_years": MAX_TERM_YEARS,
        "min_loan_rub": MIN_LOAN_RUB,
        "existing_mortgages": existing,
        "mortgages_source": mortgages_source,
    }


@router.post("/api/mortgage/quote")
async def mortgage_quote(payload: dict) -> dict:
    """Live quote — no commitment. CIB decision if available, else local maths."""
    client_id = payload.get("client_id")
    property_price = float(payload.get("property_price_rub", 0) or 0)
    down_payment = float(payload.get("down_payment_rub", 0) or 0)
    term_years = int(payload.get("term_years", 20) or 0)

    if not client_id or property_price <= 0 or term_years <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, positive property_price_rub and term_years required",
        )

    customer = await backend_get(f"/clients/{client_id}")

    cib = await try_post(CIB_URL, "/mortgage/quote", {
        "client_id": client_id,
        "property_price_rub": property_price,
        "down_payment_rub": down_payment,
        "term_years": term_years,
    }, timeout=5.0)
    if cib:
        cib.setdefault("source", "cib")
        cib.setdefault("client_id", client_id)
        cib.setdefault("term_years", term_years)
        return cib

    q = _local_quote(customer, property_price, down_payment, term_years)
    q["client_id"] = client_id
    q["property_price_rub"] = property_price
    q["down_payment_rub"] = down_payment
    return q


@router.post("/api/mortgage/apply")
async def mortgage_apply(payload: dict) -> dict:
    """Submit a mortgage application: decision via CIB, storage via backend."""
    client_id = payload.get("client_id")
    property_price = float(payload.get("property_price_rub", 0) or 0)
    down_payment = float(payload.get("down_payment_rub", 0) or 0)
    term_years = int(payload.get("term_years", 20) or 0)

    if not client_id or property_price <= 0 or term_years <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, positive property_price_rub and term_years required",
        )

    customer = await backend_get(f"/clients/{client_id}")

    # 1. Decision (cib if available, else local quote)
    cib = await try_post(CIB_URL, "/mortgage/apply", {
        "client_id": client_id,
        "property_price_rub": property_price,
        "down_payment_rub": down_payment,
        "term_years": term_years,
    }, timeout=5.0)
    if cib:
        decision = cib
        decision.setdefault("source", "cib")
    else:
        decision = _local_quote(customer, property_price, down_payment, term_years)
        decision["client_id"] = client_id
        decision["property_price_rub"] = property_price
        decision["down_payment_rub"] = down_payment

    if not decision.get("approved"):
        return {
            "status": "declined",
            "client_id": client_id,
            "reasons": decision.get("reasons", []),
            "rate_pct": decision.get("rate_pct"),
            "loan_amount_rub": decision.get("loan_amount_rub"),
            "monthly_payment_rub": decision.get("monthly_payment_rub"),
            "dti_pct": decision.get("dti_pct"),
            "ltv_pct": decision.get("ltv_pct"),
            "source": decision.get("source", "retail-heuristic"),
        }

    # 2. Persist on backend if it offers the endpoint
    storage = await try_post(BACKEND_URL, f"/clients/{client_id}/mortgages", {
        "property_price_rub": property_price,
        "down_payment_rub": down_payment,
        "loan_amount_rub": decision.get("loan_amount_rub"),
        "rate_pct": decision.get("rate_pct"),
        "term_years": term_years,
        "monthly_payment_rub": decision.get("monthly_payment_rub"),
    })
    if storage:
        return {
            "status": "approved",
            "client_id": client_id,
            "mortgage_id": storage.get("mortgage_id") or storage.get("id"),
            "loan_amount_rub": decision.get("loan_amount_rub"),
            "rate_pct": decision.get("rate_pct"),
            "term_years": term_years,
            "monthly_payment_rub": decision.get("monthly_payment_rub"),
            "total_to_pay_rub": decision.get("total_to_pay_rub"),
            "ltv_pct": decision.get("ltv_pct"),
            "dti_pct": decision.get("dti_pct"),
            "source": "cib+backend" if decision.get("source") == "cib" else "backend",
        }

    return {
        "status": "approved",
        "client_id": client_id,
        "loan_amount_rub": decision.get("loan_amount_rub"),
        "rate_pct": decision.get("rate_pct"),
        "term_years": term_years,
        "monthly_payment_rub": decision.get("monthly_payment_rub"),
        "total_to_pay_rub": decision.get("total_to_pay_rub"),
        "ltv_pct": decision.get("ltv_pct"),
        "dti_pct": decision.get("dti_pct"),
        "message": "Approved (storage pending — backend mortgage endpoint not yet available)",
        "source": decision.get("source", "retail-heuristic"),
    }
