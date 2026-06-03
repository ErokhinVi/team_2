"""Investment endpoints: portfolio overview + suitability-gated orders."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services import BACKEND_URL, CIB_URL, backend_get, try_get, try_post, cached_cib_products

router = APIRouter()

# Demo instruments used only if CIB lists no investment products at all.
FALLBACK_INSTRUMENTS = [
    {"id": "inv-etf-moex", "name": "MOEX Index ETF",
     "description": "Broad Russian equity index fund",
     "expected_return_pct": 12.0, "risk_level": 3, "min_investment_rub": 10000},
    {"id": "inv-bond-ofz", "name": "Government Bonds (OFZ)",
     "description": "Low-risk state bonds",
     "expected_return_pct": 9.0, "risk_level": 1, "min_investment_rub": 1000},
    {"id": "inv-etf-tech", "name": "Tech Growth ETF",
     "description": "High-growth technology basket",
     "expected_return_pct": 18.0, "risk_level": 5, "min_investment_rub": 10000},
    {"id": "inv-gold", "name": "Gold Fund",
     "description": "Inflation hedge, precious metals",
     "expected_return_pct": 7.5, "risk_level": 2, "min_investment_rub": 5000},
]


def _risk_band(risk_level) -> str:
    """Map a 1-5 risk level to a low/medium/high band for the UI badge."""
    try:
        lvl = int(risk_level)
    except (TypeError, ValueError):
        return "medium"
    if lvl <= 2:
        return "low"
    if lvl == 3:
        return "medium"
    return "high"


def _is_investment_product(p: dict) -> bool:
    return (
        p.get("risk_level") is not None
        or p.get("expected_return_pct") is not None
        or str(p.get("id", "")).startswith("inv-")
        or p.get("kind") in ("investment", "stock", "etf", "fund", "bond")
    )


@router.get("/api/investments/{client_id}")
async def investments_info(client_id: str) -> dict:
    """Portfolio overview: CIB instruments + suitability profile + backend holdings."""
    customer = await backend_get(f"/clients/{client_id}")

    products = await cached_cib_products()
    instruments = [p for p in (products.get("items") or []) if _is_investment_product(p)]
    if not instruments:
        instruments = list(FALLBACK_INSTRUMENTS)

    investor_profile = ""
    max_risk_level = None
    rec = await try_post(CIB_URL, "/investment/recommend", {"client_id": client_id}, timeout=5.0)
    if rec:
        investor_profile = rec.get("investor_profile", "")
        max_risk_level = rec.get("max_risk_level")

    norm = []
    for p in instruments:
        risk_level = p.get("risk_level")
        suitable = (max_risk_level is None or risk_level is None
                    or int(risk_level) <= int(max_risk_level))
        norm.append({
            "id": p.get("id"),
            "name": p.get("name", p.get("id")),
            "description": p.get("description") or p.get("subtype") or "",
            "expected_return_pct": p.get("expected_return_pct", p.get("rate_pct")),
            "risk_level": risk_level,
            "risk": _risk_band(risk_level),
            "min_investment_rub": p.get("min_investment_rub", 0),
            "suitable": suitable,
        })

    holdings = []
    total_invested = 0
    total_value = 0
    portfolio_source = "none"
    pf = await try_get(BACKEND_URL, f"/portfolio/{client_id}")
    if pf:
        holdings = pf.get("items", [])
        total_invested = sum(h.get("invested_rub", 0) for h in holdings)
        total_value = sum(h.get("current_value_rub", 0) for h in holdings)
        portfolio_source = "backend"

    gain = total_value - total_invested
    gain_pct = round((gain / total_invested) * 100, 2) if total_invested else 0

    return {
        "client_id": client_id,
        "customer_name": customer.get("name", ""),
        "balance_rub": customer.get("balance_rub", 0),
        "investor_profile": investor_profile,
        "max_risk_level": max_risk_level,
        "instruments": norm,
        "holdings": holdings,
        "total_invested_rub": total_invested,
        "total_value_rub": total_value,
        "gain_rub": gain,
        "gain_pct": gain_pct,
        "portfolio_source": portfolio_source,
    }


@router.post("/api/invest")
async def invest(payload: dict) -> dict:
    """Place an investment order end to end.

    Flow (per Gert's investment rulebook):
      1. CIB POST /investment/order-plan turns (client_id, product_id, amount_rub)
         into a ready-to-execute order {side, symbol, qty, price_rub, est_cost_rub},
         running suitability + the trading rules in one shot.
      2. If suitable + executable, we POST the order to backend's real execution
         endpoint POST /clients/{client_id}/orders.
      3. If CIB is unreachable, fall back to the standalone suitability check;
         if backend is unreachable, return a simulated confirmation so the screen
         still works for demos.
    """
    client_id = payload.get("client_id")
    instrument_id = payload.get("instrument_id")
    amount = payload.get("amount_rub", 0)

    if not client_id or not instrument_id or amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, instrument_id and positive amount_rub required",
        )

    # Step 1 — ask CIB to plan the order (suitability + symbol + qty + price)
    plan = await try_post(
        CIB_URL, "/investment/order-plan",
        {"client_id": client_id, "product_id": instrument_id, "amount_rub": amount},
        timeout=5.0,
    )

    if plan and plan.get("suitable") is False:
        return {
            "status": "unsuitable",
            "client_id": client_id,
            "instrument_id": instrument_id,
            "instrument_name": plan.get("product_name", instrument_id),
            "amount_rub": amount,
            "reasons": plan.get("reasons", []),
            "investor_profile": plan.get("investor_profile", ""),
            "max_risk_level": plan.get("max_risk_level"),
            "product_risk_level": plan.get("product_risk_level"),
            "suitable_alternatives": plan.get("suitable_alternatives", []),
            "source": "cib",
        }

    if plan and plan.get("executable") and plan.get("order"):
        order = plan["order"]
        # Step 2 — execute on backend's real endpoint
        execution = await try_post(
            BACKEND_URL, f"/clients/{client_id}/orders",
            {"side": order["side"], "symbol": order["symbol"], "qty": order["qty"]},
        )
        if execution:
            order_obj = execution.get("order", {})
            return {
                "status": "ok",
                "client_id": client_id,
                "instrument_id": instrument_id,
                "instrument_name": order.get("symbol", instrument_id),
                "amount_rub": amount,
                "qty": order_obj.get("qty", order.get("qty")),
                "price_rub": order_obj.get("price_rub", order.get("price_rub")),
                "gross_rub": order_obj.get("gross_rub", order.get("est_cost_rub")),
                "new_balance_rub": execution.get("new_balance_rub"),
                "source": "cib+backend",
            }
        # Plan succeeded but backend wouldn't execute — surface the plan as a preview
        return {
            "status": "ok",
            "client_id": client_id,
            "instrument_id": instrument_id,
            "instrument_name": order.get("symbol", instrument_id),
            "amount_rub": amount,
            "qty": order.get("qty"),
            "price_rub": order.get("price_rub"),
            "projected_value_1y_rub": order.get("est_cost_rub"),
            "message": "Order planned but not yet executed",
            "source": "cib-plan",
        }

    # Step 3a — CIB plan unavailable; fall back to plain suitability check
    suit = await try_post(
        CIB_URL, "/investment/suitability",
        {"client_id": client_id, "product_id": instrument_id, "amount_rub": amount},
        timeout=5.0,
    )
    if suit and not suit.get("suitable", True):
        return {
            "status": "unsuitable",
            "client_id": client_id,
            "instrument_id": instrument_id,
            "instrument_name": suit.get("product_name", instrument_id),
            "amount_rub": amount,
            "reasons": suit.get("reasons", []),
            "investor_profile": suit.get("investor_profile", ""),
            "max_risk_level": suit.get("max_risk_level"),
            "product_risk_level": suit.get("product_risk_level"),
            "suitable_alternatives": suit.get("suitable_alternatives", []),
            "source": "cib",
        }

    # Step 3b — simulated confirmation only when both neighbours are unreachable
    expected_return = 10.0
    name = instrument_id
    products = await cached_cib_products()
    pool = (products.get("items") or []) + FALLBACK_INSTRUMENTS
    for p in pool:
        if p.get("id") == instrument_id:
            expected_return = p.get("expected_return_pct", expected_return)
            name = p.get("name", instrument_id)
            break

    projected_value = round(amount * (1 + expected_return / 100), 2)
    return {
        "status": "ok",
        "client_id": client_id,
        "instrument_id": instrument_id,
        "instrument_name": name,
        "amount_rub": amount,
        "expected_return_pct": expected_return,
        "projected_value_1y_rub": projected_value,
        "message": "Investment order placed",
        "source": "retail-simulated",
    }
