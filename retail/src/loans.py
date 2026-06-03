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
