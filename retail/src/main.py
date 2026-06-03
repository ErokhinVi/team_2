"""Блок retail — клиентский мобильный банк команды.

Тонкий UI-слой: за данными ходит в backend, за решениями — в cib. Своих данных
не держит. Маршруты разнесены по доменным модулям (cards, savings, investments,
loans, transfers, core); общий HTTP-слой — в services.py. Это main.py только
собирает приложение: монтирует статику, отдаёт страницу и health, подключает
роутеры и middleware блокировки профиля.
"""
from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src import (brokerage, cards, carloans, core, investments, loans, locks,
                 mortgages, offers, referrals, savings, transfers)
from src.services import BACKEND_URL, CIB_URL, COMMIT, STATIC_DIR, TEAM_NAME

app = FastAPI(title="retail — мобильный банк", version="2.1.0")

# ---- Blue / green deployment ----
# Production assets live in src/static/ and are served at "/" + "/static/*".
# A staging copy lives in src/staging/ and is served at "/preview" +
# "/static-preview/*". Push experimental UI into staging, test against the
# live backend at /preview, then promote by copying staging → static.
STAGING_DIR = STATIC_DIR.parent / "staging"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if STAGING_DIR.exists():
    app.mount("/static-preview", StaticFiles(directory=STAGING_DIR), name="static-preview")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "team": TEAM_NAME, "block": "retail",
            "commit": COMMIT, "backend_url": BACKEND_URL, "cib_url": CIB_URL}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    f = STATIC_DIR / "index.html"
    return f.read_text(encoding="utf-8") if f.exists() else "<h1>Розница</h1>"


@app.get("/preview", response_class=HTMLResponse)
async def preview() -> str:
    """Serve the staging copy of the UI for blue/green testing."""
    f = STAGING_DIR / "index.html"
    if not f.exists():
        return "<h1>preview not available</h1>"
    html = f.read_text(encoding="utf-8")
    # Inject a small "preview" badge so it's obvious which build is on screen.
    badge = (
        '<div style="position:fixed;top:8px;left:8px;z-index:9999;'
        'background:#1c1a15;color:#FFE600;font-family:system-ui,sans-serif;'
        'font-size:10px;font-weight:700;letter-spacing:.08em;'
        'padding:3px 9px;border-radius:12px;text-transform:uppercase;">'
        'preview</div>'
    )
    return html.replace("</body>", badge + "</body>", 1)


# ---- Profile-lock endpoints ----
@app.post("/api/lock/acquire")
async def lock_acquire(payload: dict, request: Request) -> dict:
    client_id = payload.get("client_id")
    session_id = request.headers.get("x-session-id") or payload.get("session_id")
    holder = payload.get("holder_label", "")
    if not client_id or not session_id:
        return JSONResponse(status_code=400,
                            content={"detail": "client_id and X-Session-Id required"})
    res = await locks.acquire(client_id, session_id, holder)
    if res.get("ok"):
        return res
    return JSONResponse(status_code=423, content=res)


@app.post("/api/lock/release")
async def lock_release(payload: dict, request: Request) -> dict:
    client_id = payload.get("client_id")
    session_id = request.headers.get("x-session-id") or payload.get("session_id")
    if not client_id or not session_id:
        return JSONResponse(status_code=400,
                            content={"detail": "client_id and X-Session-Id required"})
    return await locks.release(client_id, session_id)


@app.post("/api/lock/heartbeat")
async def lock_heartbeat(payload: dict, request: Request) -> dict:
    return await lock_acquire(payload, request)


@app.get("/api/lock/{client_id}")
async def lock_status(client_id: str, request: Request) -> dict:
    session_id = request.headers.get("x-session-id")
    return await locks.status(client_id, session_id)


# ---- Lock-enforcement middleware ----
# Any POST under /api/ that names a client_id (in body) is rejected with 423
# when another session holds the lease. Lock endpoints themselves are skipped.
_LOCK_BYPASS_PREFIXES = ("/api/lock/", "/api/offers/")


@app.middleware("http")
async def enforce_profile_lock(request: Request, call_next):
    path = request.url.path
    if request.method == "POST" and path.startswith("/api/") and not any(
        path.startswith(p) for p in _LOCK_BYPASS_PREFIXES
    ):
        session_id = request.headers.get("x-session-id")
        body = await request.body()

        # Restore body so the route handler can read it again.
        async def _receive():
            return {"type": "http.request", "body": body, "more_body": False}
        request._receive = _receive  # type: ignore[attr-defined]

        try:
            data = json.loads(body or b"{}")
        except Exception:
            data = {}
        client_id = (
            data.get("client_id")
            or data.get("from_client_id")
            or data.get("for_client_id")
        )
        if client_id and not await locks.is_allowed(client_id, session_id):
            return JSONResponse(
                status_code=423,
                content={"detail": "Profile is in use by another session"},
            )

    return await call_next(request)


# Domain routers — adding a feature = add a module and include it here.
for _router in (
    core.router,
    offers.router,
    transfers.router,
    cards.router,
    savings.router,
    investments.router,
    brokerage.router,
    loans.router,
    carloans.router,
    mortgages.router,
    referrals.router,
):
    app.include_router(_router)
