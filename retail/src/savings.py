"""Savings / deposit endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services import BACKEND_URL, CIB_URL, backend_get, try_get, try_post
from src.smart_engine import _stats as engine_stats, cached_cib_products

router = APIRouter()


@router.get("/api/deposits/{client_id}")
async def deposits_info(client_id: str) -> dict:
    """Savings overview: deposit products from CIB + existing deposits from backend."""
    customer = await backend_get(f"/clients/{client_id}")

    products = await cached_cib_products()
    deposit_products = [
        p for p in (products.get("items") or [])
        if p.get("kind") in ("deposit", "savings")
    ]

    existing_deposits = []
    total_deposited = 0
    total_interest = 0
    deposits_source = "none"
    dep_data = await try_get(BACKEND_URL, f"/clients/{client_id}/deposits")
    if dep_data:
        # Backend fields: deposit_id, product, amount_rub, term_months, rate_pct,
        # status, opened_at, matures_at. Normalise so the UI gets product_name
        # and the flag whether the deposit can still be withdrawn.
        prod_by_id = {p.get("id"): p for p in deposit_products}
        for d in dep_data.get("items", []):
            pid = d.get("product")
            prod = prod_by_id.get(pid, {})
            existing_deposits.append({
                **d,
                "product_id": pid,
                "product_name": prod.get("name", pid),
                "is_open": d.get("status") in (None, "", "open", "active"),
            })
        total_deposited = sum(d.get("amount_rub", 0) for d in existing_deposits if d["is_open"])
        total_interest = sum(d.get("interest_earned_rub", 0) for d in existing_deposits)
        deposits_source = "backend"

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


@router.post("/api/deposit-open")
async def deposit_open(payload: dict) -> dict:
    """Open a deposit: CIB /deposit/open, else backend /deposits, else simulated."""
    client_id = payload.get("client_id")
    product_id = payload.get("product_id")
    amount = payload.get("amount_rub", 0)
    term_months = payload.get("term_months", 12)

    if not client_id or not product_id or amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, product_id and positive amount_rub required",
        )

    # Smart engine: record conversion (self-improving feedback loop)
    import time
    engine_stats[product_id]["conversions"] += 1
    engine_stats[product_id]["last_boost"] = time.time()

    cib = await try_post(
        CIB_URL, "/deposit/open",
        {"client_id": client_id, "product_id": product_id, "amount_rub": amount},
    )
    if cib:
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

    backend = await try_post(BACKEND_URL, "/deposits", payload)
    if backend:
        return backend

    # Simulated fallback — derive rate from the CIB catalogue if possible
    rate_pct = 14.0
    products = await cached_cib_products()
    for p in products.get("items", []):
        if p.get("id") == product_id and p.get("rate_pct"):
            rate_pct = p["rate_pct"]
            break

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


@router.post("/api/deposit-withdraw")
async def deposit_withdraw(payload: dict) -> dict:
    """Close a deposit and return funds + interest to the customer.

    Routes through CIB POST /deposit/withdraw (which proxies to backend so the
    money actually moves). Falls back to backend POST /api/deposits/{id}/withdraw
    if CIB is unreachable.
    """
    deposit_id = payload.get("deposit_id")
    early = bool(payload.get("early", False))
    if not deposit_id:
        raise HTTPException(status_code=400, detail="deposit_id required")

    cib = await try_post(CIB_URL, "/deposit/withdraw",
                         {"deposit_id": deposit_id, "early": early})
    if cib:
        return {**cib, "source": cib.get("source", "cib")}

    backend = await try_post(BACKEND_URL, f"/api/deposits/{deposit_id}/withdraw",
                             {"early": early})
    if backend:
        return {**backend, "source": "backend"}

    raise HTTPException(status_code=502, detail="Could not close deposit")
