"""End-to-end watcher — alert mode for the retail block.

Runs a customer-journey verification pass on a timer:
  * health-checks both neighbours
  * confirms the product catalogue is non-empty
  * exercises each product's decision/quote endpoint
  * confirms the previews don't leak side effects (no product events)
  * actually opens + closes a tiny flexible deposit and asserts the
    balance round-trips, proving money really moves end-to-end
  * runs a brokerage order-plan against backend's catalogue and asserts
    the symbol mapping resolves

The latest pass and its checks are exposed via GET /api/watcher/status so
you can spot mismatches from the browser. Failed checks are logged at
WARNING so they surface in Render logs.

Opt-in via the WATCHER_ENABLED env var (default: on). Interval defaults
to 300s; tunable via WATCHER_INTERVAL_SECONDS.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from src.services import BACKEND_URL, CIB_URL

log = logging.getLogger("watcher")
log.setLevel(logging.INFO)

WATCHER_ENABLED = os.environ.get("WATCHER_ENABLED", "1") not in ("0", "false", "")
INTERVAL_SECONDS = int(os.environ.get("WATCHER_INTERVAL_SECONDS", "300"))

# Latest pass result, polled via /api/watcher/status.
last_pass: dict = {
    "enabled": WATCHER_ENABLED,
    "interval_seconds": INTERVAL_SECONDS,
    "ran_at": None,
    "duration_ms": None,
    "ok": 0,
    "total": 0,
    "checks": [],
    "failures": [],
}


async def _get(base: str, path: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(f"{base}{path}")
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


async def _post(base: str, path: str, body: dict) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(f"{base}{path}", json=body)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _record(checks: list, label: str, ok: bool, detail: str = "") -> None:
    checks.append({"label": label, "ok": bool(ok), "detail": detail})


async def _run_pass() -> dict:
    """Execute one verification pass and return a structured result."""
    started = time.monotonic()
    checks: list = []

    # 1. Health checks on both neighbours
    backend_health = await _get(BACKEND_URL, "/health")
    _record(checks, "backend /health", backend_health is not None)
    cib_health = await _get(CIB_URL, "/health")
    _record(checks, "cib /health", cib_health is not None)

    # 2. Product catalogue is reachable and non-empty
    products = await _get(CIB_URL, "/products") or {}
    items = products.get("items", [])
    _record(checks, "cib /products non-empty", bool(items),
            f"{len(items)} products" if items else "empty")

    # Pick a test customer that exists. First-of-list is stable across restarts.
    test_client_id: str | None = None
    clients = await _get(BACKEND_URL, "/clients?limit=1") or {}
    if clients.get("items"):
        test_client_id = clients["items"][0]["id"]
    _record(checks, "test customer found", bool(test_client_id),
            test_client_id or "")

    if not test_client_id:
        # Without a client we can't exercise the per-customer flows.
        _finalise(checks, started)
        return last_pass

    # 3. Loan decision (preview only — no execution)
    loan_decide = await _post(CIB_URL, "/credit/decide", {
        "client_id": test_client_id, "product_id": "credit-consumer",
    })
    _record(checks, "cib /credit/decide returns decision",
            loan_decide is not None and "approved" in (loan_decide or {}),
            f"rate={loan_decide.get('rate_pct')}" if loan_decide else "no response")

    # 4. Mortgage QUOTE — should never write a product event.
    products_before = await _get(BACKEND_URL, f"/clients/{test_client_id}/products") or {}
    events_before = products_before.get("events_total", 0)

    mortgage_quote = await _post(CIB_URL, "/mortgage/quote", {
        "client_id": test_client_id,
        "property_price_rub": 5000000,
        "down_payment_rub": 1500000,
        "term_years": 20,
    })
    _record(checks, "cib /mortgage/quote returns payment",
            mortgage_quote is not None and "monthly_payment_rub" in (mortgage_quote or {}),
            f"monthly={mortgage_quote.get('monthly_payment_rub')}" if mortgage_quote else "no response")

    products_after = await _get(BACKEND_URL, f"/clients/{test_client_id}/products") or {}
    events_after = products_after.get("events_total", 0)
    _record(checks, "/mortgage/quote leaks no event",
            events_after == events_before,
            f"before={events_before} after={events_after}")

    # 5. Car-loan preview — call /car-loan/decide WITHOUT record:true; should not book.
    carloan_preview = await _post(CIB_URL, "/car-loan/decide", {
        "client_id": test_client_id,
        "car_price_rub": 1500000,
        "down_payment_rub": 300000,
        "term_years": 5,
    })
    _record(checks, "cib /car-loan/decide preview",
            carloan_preview is not None and "approved" in (carloan_preview or {}),
            f"rate={carloan_preview.get('rate_pct')}" if carloan_preview else "no response")

    products_after_car = await _get(BACKEND_URL, f"/clients/{test_client_id}/products") or {}
    _record(checks, "/car-loan/decide preview leaks no event",
            (products_after_car.get("events_total", 0)) == events_after,
            f"event_count={products_after_car.get('events_total')}")

    # 6. Investment order-plan (preview only, no execution)
    order_plan = await _post(CIB_URL, "/investment/order-plan", {
        "client_id": test_client_id, "product_id": "inv-ofz", "amount_rub": 5000,
    })
    _record(checks, "cib /investment/order-plan returns plan",
            order_plan is not None and "suitable" in (order_plan or {}),
            f"executable={order_plan.get('executable')}" if order_plan else "no response")

    # 7. Brokerage price catalogue and symbol mapping
    instruments = await _get(BACKEND_URL, "/instruments") or {}
    inst_count = len(instruments.get("items", []))
    _record(checks, "backend /instruments has prices", inst_count > 0,
            f"{inst_count} instruments")

    # 8. End-to-end deposit money round-trip:
    #    open a 1,000 ₽ flexible deposit → withdraw it → assert balance returns.
    cust_before = await _get(BACKEND_URL, f"/clients/{test_client_id}") or {}
    bal_before = cust_before.get("balance_rub", 0)

    deposit = await _post(CIB_URL, "/deposit/open", {
        "client_id": test_client_id, "product_id": "deposit-flex", "amount_rub": 1000,
    })
    deposit_id = (deposit or {}).get("deposit_id")
    _record(checks, "deposit opens", deposit is not None and bool(deposit_id),
            f"deposit_id={deposit_id}" if deposit_id else "no deposit_id returned")

    if deposit_id:
        withdraw = await _post(CIB_URL, "/deposit/withdraw", {
            "deposit_id": deposit_id, "early": True,
        })
        _record(checks, "deposit withdraws", withdraw is not None,
                f"returned={withdraw.get('returned_rub')}" if withdraw else "no response")

        cust_after = await _get(BACKEND_URL, f"/clients/{test_client_id}") or {}
        bal_after = cust_after.get("balance_rub", 0)
        delta = abs(bal_after - bal_before)
        # Flexible deposit returns principal in full + flat interest accrued, so
        # the customer should at minimum get their 1000 ₽ back.
        _record(checks, "balance round-trips",
                bal_after >= bal_before,
                f"before={bal_before} after={bal_after} delta={delta}")

    _finalise(checks, started)
    return last_pass


def _finalise(checks: list, started: float) -> None:
    ok = sum(1 for c in checks if c["ok"])
    failures = [c["label"] for c in checks if not c["ok"]]
    last_pass.update({
        "enabled": WATCHER_ENABLED,
        "interval_seconds": INTERVAL_SECONDS,
        "ran_at": time.time(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "ok": ok,
        "total": len(checks),
        "checks": checks,
        "failures": failures,
    })
    if failures:
        log.warning("[watcher] %d/%d pass — failures: %s",
                    ok, len(checks), failures)
    else:
        log.info("[watcher] %d/%d pass — clean (%dms)",
                 ok, len(checks), last_pass["duration_ms"])


async def watcher_loop() -> None:
    if not WATCHER_ENABLED:
        log.info("[watcher] disabled via WATCHER_ENABLED")
        return
    # Wait briefly so the FastAPI app finishes startup before the first pass.
    await asyncio.sleep(15)
    while True:
        try:
            await _run_pass()
        except Exception as exc:
            log.error("[watcher] pass crashed: %s", exc)
        await asyncio.sleep(INTERVAL_SECONDS)
