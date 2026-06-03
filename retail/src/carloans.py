"""Car-loan endpoints: live monthly-payment calculator + application.

Mirrors the mortgage flow but with shorter terms, higher rates, and a smaller
minimum down payment — the car itself is collateral.

Wires through:
  * CIB POST /car-loan/decide      — decision + monthly payment (when shipped)
  * Reads existing car loans from backend's customer product-event log
    (GET /clients/{id}/products), the same place Gert records mortgages.

Until cib ships /car-loan/decide, falls back to a transparent local annuity
calculation so the screen is fully usable end-to-end immediately.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services import BACKEND_URL, CIB_URL, backend_get, try_get, try_post, cached_cib_products

router = APIRouter()

# Fallback policy — typical RU auto-loan terms
DEFAULT_RATE_PCT = 18.9
MIN_DOWN_PAYMENT_PCT = 10.0
MAX_DTI_PCT = 45.0
MIN_TERM_YEARS = 1
MAX_TERM_YEARS = 7
MIN_LOAN_RUB = 100_000
PRODUCT_KEYWORDS = ("car-loan", "car-credit", "auto-loan", "autoloan", "car loan", "автокредит")


def _monthly_payment(principal: float, annual_rate_pct: float, term_months: int) -> float:
    if term_months <= 0 or principal <= 0:
        return 0.0
    r = (annual_rate_pct / 100.0) / 12.0
    if r == 0:
        return round(principal / term_months, 2)
    factor = (1 + r) ** term_months
    return round(principal * (r * factor) / (factor - 1), 2)


def _local_quote(customer: dict, car_price: float, down_payment: float,
                 term_years: int, rate_pct: float | None = None) -> dict:
    rate = rate_pct if rate_pct is not None else DEFAULT_RATE_PCT
    loan = round(car_price - down_payment, 2)
    term_months = term_years * 12
    monthly = _monthly_payment(loan, rate, term_months)
    total_to_pay = round(monthly * term_months, 2)
    total_interest = round(total_to_pay - loan, 2)
    ltv_pct = round((loan / car_price) * 100, 2) if car_price > 0 else 0
    income = customer.get("income_rub", 0) or 0
    dti_pct = round((monthly / income) * 100, 2) if income > 0 else None
    has_overdue = customer.get("has_overdue_history", False)

    reasons = []
    if loan < MIN_LOAN_RUB:
        reasons.append(f"loan below minimum ({loan} < {MIN_LOAN_RUB})")
    if term_years < MIN_TERM_YEARS or term_years > MAX_TERM_YEARS:
        reasons.append(f"term must be between {MIN_TERM_YEARS} and {MAX_TERM_YEARS} years")
    if down_payment < 0 or (car_price > 0 and (down_payment / car_price * 100) < MIN_DOWN_PAYMENT_PCT):
        reasons.append(f"down payment below {MIN_DOWN_PAYMENT_PCT}% of car price")
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


def _validate(client_id: str, car_price: float, term_years: int) -> None:
    if not client_id or car_price <= 0 or term_years <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, positive car_price_rub and term_years required",
        )


async def _decide(client_id: str, car_price: float, down_payment: float, term_years: int) -> dict:
    """Route the car-loan decision through CIB's /credit/decide using the
    `credit-auto` product (13.9% base, risk-priced). Retail computes the
    monthly payment from CIB's personalised rate."""
    cib = await try_post(CIB_URL, "/credit/decide",
                         {"client_id": client_id, "product_id": "credit-auto"},
                         timeout=5.0)
    if cib:
        approved = bool(cib.get("approved"))
        rate_pct = cib.get("rate_pct", DEFAULT_RATE_PCT)
        base_rate_pct = cib.get("base_rate_pct")
        loan = max(car_price - down_payment, 0)
        term_months = term_years * 12
        monthly = _monthly_payment(loan, rate_pct, term_months) if approved else 0
        total = round(monthly * term_months, 2) if approved else 0
        customer = await backend_get(f"/clients/{client_id}")
        income = customer.get("income_rub", 0) or 0
        # Pre-flight checks Gert's credit/decide doesn't enforce (down payment + DTI)
        extra_reasons = []
        if approved:
            if car_price > 0 and (down_payment / car_price * 100) < MIN_DOWN_PAYMENT_PCT:
                extra_reasons.append(f"down payment below {MIN_DOWN_PAYMENT_PCT}% of car price")
            if loan < MIN_LOAN_RUB:
                extra_reasons.append(f"loan below minimum ({loan} < {MIN_LOAN_RUB})")
            dti_pct = round((monthly / income) * 100, 2) if income > 0 else None
            if dti_pct is not None and dti_pct > MAX_DTI_PCT:
                extra_reasons.append(f"DTI {dti_pct}% exceeds maximum {MAX_DTI_PCT}%")
        if extra_reasons:
            approved = False
        ltv_pct = round((loan / car_price) * 100, 2) if car_price > 0 else 0
        dti_pct = round((monthly / income) * 100, 2) if income > 0 and monthly else None
        return {
            "approved": approved,
            "client_id": cib.get("client_id", client_id),
            "product_id": "credit-auto",
            "rate_pct": rate_pct,
            "base_rate_pct": base_rate_pct,
            "loan_amount_rub": loan,
            "monthly_payment_rub": monthly,
            "total_to_pay_rub": total,
            "ltv_pct": ltv_pct,
            "dti_pct": dti_pct,
            "term_years": term_years,
            "term_months": term_months,
            "reasons": list(cib.get("reasons", []) or []) + extra_reasons,
            "explanation": cib.get("explanation", ""),
            "customer_name": cib.get("customer_name", ""),
            "car_price_rub": car_price,
            "down_payment_rub": down_payment,
            "source": "cib",
        }

    # CIB unreachable — local fallback
    customer = await backend_get(f"/clients/{client_id}")
    q = _local_quote(customer, car_price, down_payment, term_years)
    q["client_id"] = client_id
    q["car_price_rub"] = car_price
    q["down_payment_rub"] = down_payment
    return q


@router.get("/api/car-loan/{client_id}")
async def car_loan_info(client_id: str) -> dict:
    """Car-loan screen overview: customer profile + bank policy + existing loans."""
    customer = await backend_get(f"/clients/{client_id}")

    # Existing car loans from the customer's product log
    existing = []
    products_log = await try_get(BACKEND_URL, f"/clients/{client_id}/products") or {}
    for ev in products_log.get("events", []):
        product = (ev.get("product") or "").lower()
        if not any(k in product for k in PRODUCT_KEYWORDS):
            continue
        details = ev.get("details") or {}
        existing.append({
            "id": ev.get("event_id"),
            "opened_at": ev.get("opened_at"),
            "product": ev.get("product"),
            "product_name": "Car loan",
            "loan_amount_rub": details.get("loan_amount_rub") or details.get("amount_rub"),
            "rate_pct": details.get("rate_pct"),
            "term_years": details.get("term_years"),
            "monthly_payment_rub": details.get("monthly_payment_rub"),
            "car_price_rub": details.get("car_price_rub"),
            "down_payment_rub": details.get("down_payment_rub"),
        })

    # Pull bank's car-loan rate from cib catalogue if present
    rate_pct = DEFAULT_RATE_PCT
    cat = await cached_cib_products()
    for p in cat.get("items", []):
        pid = str(p.get("id", "")).lower()
        kind = str(p.get("kind", "")).lower()
        if kind == "car-loan" or kind == "auto-loan" or "car" in pid or "auto" in pid:
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
        "existing_loans": existing,
        "loans_source": "backend-products" if products_log else "none",
    }


@router.post("/api/car-loan/quote")
async def car_loan_quote(payload: dict) -> dict:
    client_id = payload.get("client_id")
    car_price = float(payload.get("car_price_rub", 0) or 0)
    down_payment = float(payload.get("down_payment_rub", 0) or 0)
    term_years = int(payload.get("term_years", 5) or 0)
    _validate(client_id, car_price, term_years)
    return await _decide(client_id, car_price, down_payment, term_years)


@router.post("/api/car-loan/apply")
async def car_loan_apply(payload: dict) -> dict:
    """Submit a car-loan application via CIB. CIB records the loan on the
    customer profile on approval (same pattern as mortgages)."""
    client_id = payload.get("client_id")
    car_price = float(payload.get("car_price_rub", 0) or 0)
    down_payment = float(payload.get("down_payment_rub", 0) or 0)
    term_years = int(payload.get("term_years", 5) or 0)
    _validate(client_id, car_price, term_years)

    decision = await _decide(client_id, car_price, down_payment, term_years)

    if not decision.get("approved"):
        return {
            "status": "declined",
            "client_id": client_id,
            "reasons": decision.get("reasons", []),
            "explanation": decision.get("explanation", ""),
            "rate_pct": decision.get("rate_pct"),
            "loan_amount_rub": decision.get("loan_amount_rub"),
            "monthly_payment_rub": decision.get("monthly_payment_rub"),
            "term_years": decision.get("term_years", term_years),
            "ltv_pct": decision.get("ltv_pct"),
            "dti_pct": decision.get("dti_pct"),
            "source": decision.get("source", "retail-heuristic"),
        }

    # Best-effort: if CIB didn't record it on the profile (fallback path),
    # write the event ourselves so the loan shows up on the screen later.
    if decision.get("source") != "cib":
        await try_post(
            BACKEND_URL, f"/clients/{client_id}/products",
            {
                "product": "car-loan",
                "source": "retail",
                "details": {
                    "loan_amount_rub": decision.get("loan_amount_rub"),
                    "rate_pct": decision.get("rate_pct"),
                    "term_years": decision.get("term_years", term_years),
                    "monthly_payment_rub": decision.get("monthly_payment_rub"),
                    "car_price_rub": car_price,
                    "down_payment_rub": down_payment,
                },
            },
        )

    return {
        "status": "approved",
        "client_id": client_id,
        "product_id": decision.get("product_id", "car-loan"),
        "loan_amount_rub": decision.get("loan_amount_rub"),
        "rate_pct": decision.get("rate_pct"),
        "term_years": decision.get("term_years", term_years),
        "monthly_payment_rub": decision.get("monthly_payment_rub"),
        "total_to_pay_rub": decision.get("total_to_pay_rub"),
        "down_payment_pct": decision.get("down_payment_pct"),
        "ltv_pct": decision.get("ltv_pct"),
        "dti_pct": decision.get("dti_pct"),
        "explanation": decision.get("explanation", ""),
        "customer_name": decision.get("customer_name", ""),
        "source": decision.get("source", "retail-heuristic"),
    }
