"""Блок retail — клиентский мобильный банк команды.

Тонкий UI-слой: за данными ходит в backend, за решениями — в cib. Своих данных
не держит. Маршруты разнесены по доменным модулям (cards, savings, investments,
loans, transfers, core); общий HTTP-слой — в services.py. Это main.py только
собирает приложение: монтирует статику, отдаёт страницу и health, подключает
роутеры.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src import (brokerage, cards, core, investments, loans, mortgages,
                 offers, savings, transfers)
from src.services import BACKEND_URL, CIB_URL, COMMIT, STATIC_DIR, TEAM_NAME

app = FastAPI(title="retail — мобильный банк", version="2.0.0")

# Static assets (styles.css, app.js, ...) live next to index.html.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "team": TEAM_NAME, "block": "retail",
            "commit": COMMIT, "backend_url": BACKEND_URL, "cib_url": CIB_URL}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    f = STATIC_DIR / "index.html"
    return f.read_text(encoding="utf-8") if f.exists() else "<h1>Розница</h1>"


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
    mortgages.router,
):
    app.include_router(_router)
