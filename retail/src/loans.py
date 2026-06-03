"""Consumer loan application (orchestrates CIB decision + backend fallback)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services import CIB_URL, backend_get, try_post

router = APIRouter()


@router.post("/api/credit-apply")
async def credit_apply(payload: dict) -> dict:
    """Loan application: CIB POST /credit/decide; local heuristic if unreachable."""
    client_id = payload.get("client_id")
    product_id = payload.get("product_id")
    amount = payload.get("amount_rub", 0)

    if not client_id or not product_id:
        raise HTTPException(status_code=400, detail="client_id and product_id required")

    cib = await try_post(
        CIB_URL, "/credit/decide",
        {"client_id": client_id, "product_id": product_id},
    )
    if cib:
        result = {
            "status": "approved" if cib.get("approved") else "declined",
            "client_id": cib.get("client_id", client_id),
            "product_id": cib.get("product_id", product_id),
            "amount_rub": amount,
            "reason": cib.get("explanation", ""),
            "reasons": cib.get("reasons", []),
            "customer_name": cib.get("customer_name", ""),
            "source": "cib",
        }
        if cib.get("rate_pct") is not None:
            result["rate_pct"] = cib["rate_pct"]
        if cib.get("base_rate_pct") is not None:
            result["base_rate_pct"] = cib["base_rate_pct"]
        return result

    # Fallback: simple heuristic when CIB is not reachable
    customer = await backend_get(f"/clients/{client_id}")
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


@router.post("/api/credit/secured-apply")
async def credit_secured_apply(payload: dict) -> dict:
    """Secured lending — borrow against a deposit or investment held with us.

    Proxies CIB POST /credit/secured-decide which returns approved + max loan
    (85% of deposit collateral, 65% of portfolio) + rate + monthly payment.
    """
    client_id = payload.get("client_id")
    amount = payload.get("amount_rub", 0)
    collateral = payload.get("collateral_rub", 0)
    collateral_type = payload.get("collateral_type")
    term_months = payload.get("term_months", 12)
    if (not client_id or amount <= 0 or collateral <= 0
            or collateral_type not in ("deposit", "investment")):
        raise HTTPException(
            status_code=400,
            detail="client_id, positive amount_rub and collateral_rub, "
                   "collateral_type ('deposit'|'investment') required",
        )

    cib = await try_post(CIB_URL, "/credit/secured-decide", {
        "client_id": client_id,
        "amount_rub": amount,
        "collateral_rub": collateral,
        "collateral_type": collateral_type,
        "term_months": term_months,
    }, timeout=5.0)
    if cib:
        return {**cib, "source": "cib"}
    raise HTTPException(status_code=502, detail="secured lending unavailable")


@router.post("/api/credit/refinance")
async def credit_refinance(payload: dict) -> dict:
    """Refinance the customer's existing debt at a lower risk-based rate.

    Proxies CIB POST /credit/refinance, which returns the new rate, monthly
    saving and total saving.
    """
    client_id = payload.get("client_id")
    current_balance = payload.get("current_balance_rub", 0)
    current_rate = payload.get("current_rate_pct", 0)
    term_months = payload.get("term_months", 36)
    if not client_id or current_balance <= 0 or current_rate <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, positive current_balance_rub and current_rate_pct required",
        )

    cib = await try_post(CIB_URL, "/credit/refinance", {
        "client_id": client_id,
        "current_balance_rub": current_balance,
        "current_rate_pct": current_rate,
        "term_months": term_months,
    })
    if cib:
        return {**cib, "source": "cib"}

    raise HTTPException(status_code=502, detail="refinance unavailable")
