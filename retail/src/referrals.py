"""Member-Get-Member (MGM) referral program.

Customers share a referral code (currently their client_id, uppercased) with
friends. When the friend enters that code on the Invite screen, both sides
earn a bonus. Retail also keeps a small in-memory log of who invited whom so
the inviter can see their list of brought-in friends.

State is in-memory (workshop scope). To make the bonus real money, backend
would need a small endpoint to credit a customer's cashback balance:

    POST /clients/{id}/credit-cashback  body {amount_rub}   → backend ask

And ideally cib would expose:

    POST /referral/validate  body {inviter_id, invitee_id}  → cib ask
       returns {allowed, bonus_rub, reasons[]}

If those land later, this module fans out to them automatically; until then,
the bonus is a virtual counter shown on the Invite screen.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from src.services import BACKEND_URL, CIB_URL, backend_get, try_post

router = APIRouter()

DEFAULT_BONUS_RUB = 500


@dataclass
class Referral:
    inviter_id: str
    invitee_id: str
    created_at: float
    bonus_paid: bool = False
    bonus_rub: int = DEFAULT_BONUS_RUB
    inviter_name: str = ""
    invitee_name: str = ""


_by_invitee: dict[str, Referral] = {}                # invitee_id -> Referral
_by_inviter: dict[str, list[Referral]] = {}          # inviter_id -> [Referral]
_mu = asyncio.Lock()


def _code(client_id: str) -> str:
    return (client_id or "").upper()


@router.get("/api/referrals/{client_id}")
async def referrals_info(client_id: str) -> dict:
    """Invite-screen overview for one customer."""
    customer = await backend_get(f"/clients/{client_id}")

    async with _mu:
        my_invited = list(_by_inviter.get(client_id, []))
        invited_by = _by_invitee.get(client_id)

    invited = [
        {
            "invitee_id": r.invitee_id,
            "invitee_name": r.invitee_name or r.invitee_id,
            "at": r.created_at,
            "bonus_rub": r.bonus_rub,
            "bonus_paid": r.bonus_paid,
        }
        for r in my_invited
    ]

    bonus_earned = sum(r.bonus_rub for r in my_invited)
    if invited_by:
        bonus_earned += invited_by.bonus_rub

    return {
        "client_id": client_id,
        "customer_name": customer.get("name", ""),
        "code": _code(client_id),
        "share_text": f"Open a Self-Driving Raif account and use my code {_code(client_id)} — we both get {DEFAULT_BONUS_RUB} ₽.",
        "invited": invited,
        "invited_count": len(invited),
        "invited_by": invited_by.inviter_id if invited_by else None,
        "inviter_name": invited_by.inviter_name if invited_by else None,
        "bonus_per_referral_rub": DEFAULT_BONUS_RUB,
        "bonus_earned_rub": bonus_earned,
    }


@router.post("/api/referrals/redeem")
async def referrals_redeem(payload: dict) -> dict:
    """The invitee enters a code: link the two customers, award the bonus."""
    client_id = payload.get("client_id")
    raw = (payload.get("code") or "").strip()
    code = raw.lower()
    if not client_id or not code:
        return {"status": "error", "reason": "code_required"}
    if code == client_id.lower():
        return {"status": "error", "reason": "self_referral"}

    # The code is the inviter's client_id (case-insensitive). Validate it exists.
    try:
        inviter = await backend_get(f"/clients/{code}")
    except HTTPException:
        return {"status": "error", "reason": "code_invalid"}

    # Ask cib if the program shipped a validator; otherwise use the default bonus.
    bonus_rub = DEFAULT_BONUS_RUB
    cib_check = await try_post(CIB_URL, "/referral/validate", {
        "inviter_id": code, "invitee_id": client_id,
    }, timeout=3.0)
    if cib_check:
        if cib_check.get("allowed") is False:
            return {"status": "error", "reason": "; ".join(cib_check.get("reasons", [])) or "not_allowed"}
        bonus_rub = cib_check.get("bonus_rub", bonus_rub)

    try:
        invitee = await backend_get(f"/clients/{client_id}")
    except HTTPException:
        return {"status": "error", "reason": "client_unknown"}

    async with _mu:
        if client_id in _by_invitee:
            return {"status": "error", "reason": "already_used"}
        ref = Referral(
            inviter_id=code,
            invitee_id=client_id,
            created_at=time.time(),
            bonus_rub=bonus_rub,
            inviter_name=inviter.get("name", code),
            invitee_name=invitee.get("name", client_id),
        )
        _by_invitee[client_id] = ref
        _by_inviter.setdefault(code, []).append(ref)

    # Best-effort: tell backend to credit both sides' cashback if the endpoint exists.
    paid = False
    pa = await try_post(BACKEND_URL, f"/clients/{code}/credit-cashback",
                        {"amount_rub": bonus_rub, "source": "referral"})
    pb = await try_post(BACKEND_URL, f"/clients/{client_id}/credit-cashback",
                        {"amount_rub": bonus_rub, "source": "referral"})
    if pa and pb:
        paid = True
        async with _mu:
            ref.bonus_paid = True

    return {
        "status": "ok",
        "inviter_id": code,
        "inviter_name": inviter.get("name", code),
        "bonus_rub": bonus_rub,
        "bonus_paid": paid,
    }
