"""Loan-protection insurance — proxies CIB POST /insurance/loan-protection-quote.

Offered at the moment of loan approval so the customer can opt in to insurance
that covers repayments on job loss / illness / death, plus earn a rate discount.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services import CIB_URL, try_post

router = APIRouter()


@router.post("/api/insurance/loan-protection-quote")
async def loan_protection_quote(payload: dict) -> dict:
    client_id = payload.get("client_id")
    amount = payload.get("loan_amount_rub", 0)
    term_months = payload.get("term_months", 0)
    if not client_id or amount <= 0 or term_months <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, positive loan_amount_rub and term_months required",
        )
    cib = await try_post(CIB_URL, "/insurance/loan-protection-quote", payload, timeout=5.0)
    if cib:
        return {**cib, "source": "cib"}
    raise HTTPException(status_code=502, detail="insurance unavailable")
