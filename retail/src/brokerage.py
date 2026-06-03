"""Brokerage: live prices, positions with P&L, and buy/sell orders.

Wires through CIB's investment rulebook and backend's real trading endpoints:
  * Prices       → backend GET /instruments
  * Portfolio    → backend GET /clients/{id}/portfolio
  * Order rules  → cib POST /investment/order-check (commission + validation)
  * Execution    → backend POST /clients/{id}/orders

Falls back gracefully if a neighbour is unreachable so the screen stays useful.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.investments import FALLBACK_INSTRUMENTS, _is_investment_product, _risk_band
from src.services import BACKEND_URL, CIB_URL, backend_get, try_get, try_post, cached_cib_products

router = APIRouter()


def _sim_price(sec_id: str) -> float:
    """Deterministic per-security price (stable across restarts)."""
    base = sum(ord(c) for c in str(sec_id)) or 1
    return round(100 + (base * 37) % 4900 + (base % 100) / 100, 2)


def _commission(notional: float) -> float:
    """Simulated brokerage commission: 0.3% of notional, min 50 ₽."""
    return round(max(notional * 0.003, 50.0), 2)


@router.get("/api/brokerage/{client_id}")
async def brokerage_info(client_id: str) -> dict:
    """Brokerage overview: cash, tradable securities w/ prices, positions, orders."""
    customer = await backend_get(f"/clients/{client_id}")

    # Real prices from backend; map ticker -> price
    inst_data = await try_get(BACKEND_URL, "/instruments") or {}
    inst_items = inst_data.get("items", []) if isinstance(inst_data, dict) else []
    price_by_symbol = {}
    inst_meta = {}
    for it in inst_items:
        sym = it.get("symbol")
        if sym is None:
            continue
        try:
            price_by_symbol[sym] = float(it.get("price_rub", 0))
        except (TypeError, ValueError):
            pass
        inst_meta[sym] = it

    # Tradable securities (CIB catalogue): merge with backend prices where possible
    products = await cached_cib_products()
    raw = [p for p in (products.get("items") or []) if _is_investment_product(p)]
    if not raw:
        raw = list(FALLBACK_INSTRUMENTS)

    # CIB ticker map (per cib contract)
    cib_to_symbol = {
        "inv-ofz": "OFZ26", "inv-corp-bond": "FXCB", "inv-etf-index": "FXIM",
        "inv-equity-fund": "FXEQ", "inv-bluechip": "SBER", "inv-growth": "YNDX",
    }

    securities = []
    for p in raw:
        pid = p.get("id")
        symbol = cib_to_symbol.get(pid) or pid
        price = price_by_symbol.get(symbol) or _sim_price(symbol)
        securities.append({
            "id": symbol,                # canonical backend ticker for trading
            "product_id": pid,           # cib id for validation calls
            "name": inst_meta.get(symbol, {}).get("name") or p.get("name", pid),
            "description": p.get("description") or p.get("subtype") or "",
            "price_rub": price,
            "risk_level": p.get("risk_level"),
            "risk": _risk_band(p.get("risk_level")),
        })

    # Real portfolio from backend
    portfolio = await try_get(BACKEND_URL, f"/clients/{client_id}/portfolio")
    positions = []
    total_value = 0.0
    total_pl = 0.0
    portfolio_source = "none"
    if portfolio:
        portfolio_source = "backend"
        for pos in portfolio.get("positions", []):
            positions.append({
                "security_id": pos.get("symbol"),
                "name": pos.get("name", pos.get("symbol")),
                "quantity": pos.get("qty", 0),
                "avg_price_rub": pos.get("avg_cost_rub", 0),
                "price_rub": pos.get("current_price_rub", 0),
                "current_value_rub": pos.get("market_value_rub", 0),
                "invested_rub": pos.get("cost_basis_rub", 0),
                "pl_rub": pos.get("unrealized_pnl_rub", 0),
            })
            total_value += pos.get("market_value_rub", 0) or 0
            total_pl += pos.get("unrealized_pnl_rub", 0) or 0

    # Orders history (optional)
    orders_data = await try_get(BACKEND_URL, f"/clients/{client_id}/orders") or {}
    orders = orders_data.get("items", [])[:10] if isinstance(orders_data, dict) else []

    return {
        "client_id": client_id,
        "customer_name": customer.get("name", ""),
        "cash_rub": customer.get("balance_rub", 0),
        "securities": securities,
        "positions": positions,
        "orders": orders,
        "total_positions_value_rub": round(total_value, 2),
        "total_pl_rub": round(total_pl, 2),
        "source": "backend" if portfolio_source == "backend" else "retail-simulated",
    }


@router.post("/api/brokerage/order")
async def brokerage_order(payload: dict) -> dict:
    """Place a buy/sell order through CIB's order-check and backend execution."""
    client_id = payload.get("client_id")
    security_id = payload.get("security_id")    # backend ticker (e.g. "FXIM")
    side = payload.get("side")
    quantity = payload.get("quantity", 0)
    product_id = payload.get("product_id")       # cib product id (e.g. "inv-etf-index")

    if not client_id or not security_id or side not in ("buy", "sell") or quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="client_id, security_id, side(buy|sell) and positive quantity required",
        )

    # Step 1 — ask CIB to validate (only if we have a product_id to validate against)
    commission = None
    if product_id:
        check = await try_post(
            CIB_URL, "/investment/order-check",
            {"client_id": client_id, "product_id": product_id,
             "side": side, "qty": quantity},
            timeout=5.0,
        )
        if check:
            if check.get("valid") is False:
                return {
                    "status": "rejected",
                    "reason": "; ".join(check.get("reasons", [])) or "Order not allowed",
                    "security_id": security_id,
                    "side": side,
                    "source": "cib",
                }
            commission = check.get("commission_rub", commission)

    # Step 2 — execute on backend's real endpoint
    execution = await try_post(
        BACKEND_URL, f"/clients/{client_id}/orders",
        {"side": side, "symbol": security_id, "qty": quantity},
    )
    if execution:
        order = execution.get("order", {})
        price = order.get("price_rub", 0)
        gross = order.get("gross_rub", price * quantity)
        if commission is None:
            commission = _commission(gross)
        total = round(gross + commission, 2) if side == "buy" else round(gross - commission, 2)
        return {
            "status": "ok",
            "client_id": client_id,
            "security_id": security_id,
            "security_name": order.get("symbol", security_id),
            "side": side,
            "quantity": order.get("qty", quantity),
            "price_rub": price,
            "notional_rub": gross,
            "commission_rub": commission,
            "total_rub": total,
            "new_balance_rub": execution.get("new_balance_rub"),
            "message": "Order executed",
            "source": "backend",
        }

    # Fallback — simulated confirmation
    price = _sim_price(security_id)
    notional = round(price * quantity, 2)
    if commission is None:
        commission = _commission(notional)
    total = round(notional + commission, 2) if side == "buy" else round(notional - commission, 2)

    customer = await backend_get(f"/clients/{client_id}")
    if side == "buy" and total > customer.get("balance_rub", 0):
        return {
            "status": "rejected",
            "reason": "insufficient_funds",
            "security_id": security_id,
            "side": side,
            "source": "retail-simulated",
        }

    return {
        "status": "ok",
        "client_id": client_id,
        "security_id": security_id,
        "security_name": security_id,
        "side": side,
        "quantity": quantity,
        "price_rub": price,
        "notional_rub": notional,
        "commission_rub": commission,
        "total_rub": total,
        "message": "Order executed",
        "source": "retail-simulated",
    }
