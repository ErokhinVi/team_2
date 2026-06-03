"""Smart Engine — self-improving feedback loop for the retail bank.

Closes the loop between recommendation → impression → click → conversion.
Tracks what offers customers engage with, boosts what works, and
surfaces promo offers for newcomers automatically.

The three blocks don't need to coordinate manually:
  - backend provides customer data + analytical recommendations
  - cib packages offers with real product terms + decisions
  - retail's Smart Engine observes customer behaviour and tunes the mix

No persistent storage needed — the engine warms up fast from live data
each time the service starts. Conversion stats accumulate in-memory and
inform offer ranking in real time.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter

from src.services import BACKEND_URL, CIB_URL, try_get, try_post

router = APIRouter()

# ---- In-memory conversion tracker ----
# product_id → {impressions, clicks, conversions, last_boost}
_stats: dict[str, dict[str, Any]] = defaultdict(
    lambda: {"impressions": 0, "clicks": 0, "conversions": 0, "last_boost": 0.0}
)

# newcomer = customer whose products list is short (< 2 products beyond defaults)
_NEWCOMER_PRODUCT_THRESHOLD = 2

# ---- Promo catalogue (retail-owned, no CIB dependency) ----
PROMO_OFFERS = [
    {
        "promo_id": "welcome-savings-20",
        "product_id": "deposit-flex",
        "kind": "deposit",
        "type": "newcomer_promo",
        "title": "Welcome Bonus Savings",
        "headline": "Open a savings account today — earn 20% for your first 3 months",
        "reason": "Special rate for new customers — 2× the standard flexible rate",
        "promo_rate_pct": 20.0,
        "standard_rate_pct": 9.5,
        "promo_term_months": 3,
        "min_amount_rub": 1000,
        "badge": "🎁 PROMO",
        "score": 0.95,
        "action": {"method": "POST", "path": "/api/deposit-open"},
    },
    {
        "promo_id": "welcome-deposit-6m",
        "product_id": "deposit-6m",
        "kind": "deposit",
        "type": "newcomer_promo",
        "title": "Newcomer Fixed Deposit",
        "headline": "Lock in 18% for 6 months — exclusively for new customers",
        "reason": "3% above standard rate, available in your first 30 days",
        "promo_rate_pct": 18.0,
        "standard_rate_pct": 15.0,
        "promo_term_months": 6,
        "min_amount_rub": 10000,
        "badge": "⭐ NEW",
        "score": 0.90,
        "action": {"method": "POST", "path": "/api/deposit-open"},
    },
    {
        "promo_id": "welcome-cashback-boost",
        "product_id": "card-debit-cashback",
        "kind": "card",
        "type": "newcomer_promo",
        "title": "Double Cashback Month",
        "headline": "Activate your debit card now — 2× cashback for 30 days",
        "reason": "Earn double on every purchase for your first month",
        "promo_cashback_multiplier": 2,
        "promo_days": 30,
        "badge": "2×",
        "score": 0.88,
        "action": {"method": "POST", "path": "/api/card-info"},
    },
    {
        "promo_id": "welcome-first-invest",
        "product_id": "inv-ofz",
        "kind": "investment",
        "type": "newcomer_promo",
        "title": "Start Investing — Zero Commission",
        "headline": "Buy government bonds commission-free — first trade on us",
        "reason": "Safest investment, ~13% return, no fees for your first purchase",
        "promo_commission_pct": 0.0,
        "standard_commission_pct": 0.15,
        "badge": "0% FEE",
        "score": 0.82,
        "action": {"method": "POST", "path": "/api/invest"},
    },
]


async def _is_newcomer(client_id: str) -> tuple[bool, dict]:
    """Check if a customer is a newcomer (few products, low engagement)."""
    customer = await try_get(BACKEND_URL, f"/clients/{client_id}")
    if not customer:
        return False, {}

    products_data = await try_get(BACKEND_URL, f"/clients/{client_id}/products")
    product_count = 0
    product_codes: set[str] = set()
    if products_data:
        product_codes = {
            e.get("product", "") for e in products_data.get("events", [])
        }
        product_count = len(product_codes)

    is_new = product_count < _NEWCOMER_PRODUCT_THRESHOLD
    return is_new, {
        "customer": customer,
        "product_count": product_count,
        "product_codes": product_codes,
    }


def _boost_score(product_id: str, base_score: float) -> float:
    """Adjust score based on observed conversion rates (the self-improving part)."""
    s = _stats[product_id]
    if s["impressions"] < 5:
        return base_score  # not enough data yet

    click_rate = s["clicks"] / max(s["impressions"], 1)
    conversion_rate = s["conversions"] / max(s["clicks"], 1)

    # Blend base score with observed performance (30% base, 70% observed)
    observed = (click_rate * 0.4 + conversion_rate * 0.6)
    return round(base_score * 0.3 + observed * 0.7, 3)


@router.get("/api/smart-offers/{client_id}")
async def smart_offers(client_id: str, limit: int = 5) -> dict:
    """The main self-improving offers endpoint.

    1. Check if the customer is a newcomer → inject promo offers
    2. Fetch standard offers from CIB / backend
    3. Re-rank everything using conversion data
    4. Record impressions for the learning loop
    """
    is_new, ctx = await _is_newcomer(client_id)
    customer = ctx.get("customer", {})
    owned_products = ctx.get("product_codes", set())

    all_offers: list[dict] = []

    # 1) Promo offers for newcomers
    if is_new:
        for promo in PROMO_OFFERS:
            # Don't offer what they already have
            if promo["product_id"] in owned_products:
                continue
            boosted_score = _boost_score(promo["promo_id"], promo["score"])
            all_offers.append({
                **promo,
                "original_score": promo["score"],
                "score": boosted_score,
                "source": "smart_engine_promo",
            })

    # 2) Standard offers from CIB
    cib_offers = await try_get(
        CIB_URL, f"/clients/{client_id}/next-best-offers",
        {"limit": str(limit + 3)},
    )
    if cib_offers:
        for o in cib_offers.get("offers", []):
            pid = (o.get("cib", {}) or {}).get("product_id") or o.get("product", "")
            boosted = _boost_score(pid, o.get("score", 0.5))
            all_offers.append({
                **o,
                "original_score": o.get("score", 0.5),
                "score": boosted,
                "source": "cib",
            })

    # 3) Fallback: raw backend recommendations
    if not cib_offers:
        backend_recs = await try_get(
            BACKEND_URL, f"/clients/{client_id}/recommendations",
            {"limit": str(limit + 3)},
        )
        if backend_recs:
            for r in backend_recs.get("recommendations", []):
                pid = r.get("product", "")
                boosted = _boost_score(pid, r.get("score", 0.5))
                all_offers.append({
                    **r,
                    "original_score": r.get("score", 0.5),
                    "score": boosted,
                    "source": "backend",
                })

    # 4) Sort by boosted score (highest first) and cap
    all_offers.sort(key=lambda o: o.get("score", 0), reverse=True)
    top = all_offers[:limit]

    # 5) Record impressions (the engine is learning)
    for o in top:
        pid = o.get("promo_id") or o.get("product_id") or o.get("product", "")
        _stats[pid]["impressions"] += 1

    return {
        "client_id": client_id,
        "customer_name": customer.get("name", ""),
        "segment": customer.get("segment", ""),
        "is_newcomer": is_new,
        "total": len(top),
        "offers": top,
        "engine": "smart_engine_v1",
        "stats_snapshot": {
            pid: {**s} for pid, s in _stats.items() if s["impressions"] > 0
        },
    }


@router.post("/api/smart-engine/click")
async def record_click(payload: dict) -> dict:
    """Record that a customer clicked on an offer (learning signal)."""
    product_id = payload.get("product_id") or payload.get("promo_id", "")
    client_id = payload.get("client_id", "")
    if product_id:
        _stats[product_id]["clicks"] += 1
        _stats[product_id]["last_boost"] = time.time()
    return {"status": "ok", "tracked": product_id, "client_id": client_id}


@router.post("/api/smart-engine/conversion")
async def record_conversion(payload: dict) -> dict:
    """Record that a customer completed an action (strongest learning signal).

    Call this after a deposit is opened, card activated, loan approved, etc.
    The engine will boost that product for similar customers.
    """
    product_id = payload.get("product_id") or payload.get("promo_id", "")
    client_id = payload.get("client_id", "")
    if product_id:
        _stats[product_id]["conversions"] += 1
        _stats[product_id]["last_boost"] = time.time()
    return {"status": "ok", "converted": product_id, "client_id": client_id}


@router.get("/api/smart-engine/stats")
async def engine_stats() -> dict:
    """Dashboard: how the self-improving engine is performing."""
    products = []
    for pid, s in _stats.items():
        imp = s["impressions"]
        clk = s["clicks"]
        conv = s["conversions"]
        products.append({
            "product_id": pid,
            "impressions": imp,
            "clicks": clk,
            "conversions": conv,
            "click_rate": round(clk / max(imp, 1), 3),
            "conversion_rate": round(conv / max(clk, 1), 3),
        })
    products.sort(key=lambda p: p["conversions"], reverse=True)

    return {
        "engine": "smart_engine_v1",
        "total_products_tracked": len(products),
        "total_impressions": sum(p["impressions"] for p in products),
        "total_clicks": sum(p["clicks"] for p in products),
        "total_conversions": sum(p["conversions"] for p in products),
        "products": products,
        "promo_catalogue_size": len(PROMO_OFFERS),
    }
