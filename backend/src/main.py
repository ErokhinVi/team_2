"""Блок backend — ядро данных банка команды.

Хранит клиентов, транзакции, балансы; отдаёт базовый API. UI нет.
Данные in-memory из seed/*.jsonl. Кредитное хранилище
(POST/GET /credit-applications) добавляет владелец блока в рамках задачи.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

TEAM_NAME = os.environ.get("TEAM_NAME", "team")
COMMIT = os.environ.get("RENDER_GIT_COMMIT", "local")

# Кешбэк: доля от суммы покупки, которая возвращается клиенту.
CASHBACK_RATE = float(os.environ.get("CASHBACK_RATE", "0.05"))
# Типы операций, на которые начисляется кешбэк (траты, а не переводы).
CASHBACK_EARNING_TYPES = {"purchase", "utility_payment"}

# Кредитные карты: продукты, владельцам которых выпускаем карту при загрузке.
CREDIT_PRODUCTS = {"consumer_credit", "auto_credit", "credit_card", "mortgage"}


def _find_seed_dir() -> Path | None:
    """Ищем seed/ — работает и в Docker (/app/seed), и локально."""
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "seed",
        here.parents[2] / "seed" if len(here.parents) >= 3 else None,
        here.parents[3] / "seed" if len(here.parents) >= 4 else None,
        here.parents[4] / "seed" if len(here.parents) >= 5 else None,
    ]
    for c in candidates:
        if c and c.exists():
            return c
    return None


SEED_DIR = _find_seed_dir()
_clients: list[dict[str, Any]] = []
_clients_by_id: dict[str, dict[str, Any]] = {}
_transactions: list[dict[str, Any]] = []
# Журнал открытых продуктов: кто, какой продукт и когда оформил.
_product_events: list[dict[str, Any]] = []
_product_events_by_client: dict[str, list[dict[str, Any]]] = {}

# Инвестиции: каталог инструментов с текущей ценой, портфели клиентов и
# журнал заявок. Цены — фиксированный каталог (для воспроизводимости);
# текущая стоимость портфеля считается по этим ценам на лету.
_instruments: dict[str, dict[str, Any]] = {
    "SBER": {"symbol": "SBER", "name": "Сбербанк, акция", "price_rub": 312},
    "GAZP": {"symbol": "GAZP", "name": "Газпром, акция", "price_rub": 168},
    "LKOH": {"symbol": "LKOH", "name": "Лукойл, акция", "price_rub": 7240},
    "YNDX": {"symbol": "YNDX", "name": "Яндекс, акция", "price_rub": 4115},
    "OFZ26": {"symbol": "OFZ26", "name": "ОФЗ, облигация", "price_rub": 985},
    "FXGD": {"symbol": "FXGD", "name": "Фонд на золото", "price_rub": 152},
    "FXCB": {"symbol": "FXCB", "name": "Фонд корпоративных облигаций", "price_rub": 1040},
    "FXIM": {"symbol": "FXIM", "name": "Индексный ETF на индекс Мосбиржи", "price_rub": 185},
    "FXEQ": {"symbol": "FXEQ", "name": "Фонд акций (широкий рынок)", "price_rub": 2450},
}
# Портфель клиента: symbol -> {symbol, qty, avg_cost_rub}.
_holdings_by_client: dict[str, dict[str, dict[str, Any]]] = {}
_orders: list[dict[str, Any]] = []
_orders_by_client: dict[str, list[dict[str, Any]]] = {}
_credit_cards: list[dict[str, Any]] = []
_cards_by_id: dict[str, dict[str, Any]] = {}
_cards_by_client: dict[str, list[dict[str, Any]]] = {}

# Вклады: списываем деньги с баланса клиента и держим их во вкладе, пока он
# не закрыт. Журнал вкладов + индексы по id и по клиенту.
_deposits: list[dict[str, Any]] = []
_deposits_by_id: dict[str, dict[str, Any]] = {}
_deposits_by_client: dict[str, list[dict[str, Any]]] = {}
# Продукты, у которых разрешено досрочное снятие без потери процентов.
DEPOSIT_FLEX_PRODUCTS = {"deposit-flex", "savings-flex"}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _load_seed() -> None:
    if not SEED_DIR:
        return
    clients = _load_jsonl(SEED_DIR / "clients.jsonl")
    for c in clients:
        c.setdefault("cashback_balance_rub", 0)
    _clients.extend(clients)
    _clients_by_id.update({c["id"]: c for c in clients})
    txs = _load_jsonl(SEED_DIR / "transactions.jsonl")
    # Ретроспективно начисляем кешбэк за прошлые траты из истории операций,
    # чтобы у клиентов сразу был ненулевой кешбэк-баланс.
    for t in txs:
        if t.get("type") in CASHBACK_EARNING_TYPES:
            earned = int(abs(int(t.get("amount_rub", 0))) * CASHBACK_RATE)
            t["cashback_rub"] = earned
            owner = _clients_by_id.get(t.get("client_id"))
            if owner:
                owner["cashback_balance_rub"] = int(
                    owner.get("cashback_balance_rub", 0)) + earned
        else:
            t["cashback_rub"] = 0
    _transactions.extend(txs)


_load_seed()


def _card_view(card: dict[str, Any], with_history: bool = False) -> dict[str, Any]:
    """Карта наружу: считаем доступный лимит на лету, чтобы не было рассинхрона."""
    view = {
        "card_id": card["card_id"],
        "client_id": card["client_id"],
        "credit_limit_rub": card["credit_limit_rub"],
        "balance_owed_rub": card["balance_owed_rub"],
        "available_credit_rub": card["credit_limit_rub"] - card["balance_owed_rub"],
        "status": card["status"],
        "opened_at": card["opened_at"],
    }
    if with_history:
        view["history"] = card["history"]
    else:
        view["history_count"] = len(card["history"])
    return view


def _issue_card(client: dict[str, Any], limit: int, opened_at: str,
                initial_owed: int = 0) -> dict[str, Any]:
    card_id = f"cc-{len(_credit_cards) + 1:06d}"
    card: dict[str, Any] = {
        "card_id": card_id,
        "client_id": client["id"],
        "credit_limit_rub": int(limit),
        "balance_owed_rub": int(initial_owed),
        "status": "active",
        "opened_at": opened_at,
        "history": [],
    }
    if initial_owed > 0:
        card["history"].append({
            "ts": f"{opened_at}T00:00:00", "type": "charge",
            "amount_rub": int(initial_owed), "note": "перенос текущей задолженности",
            "balance_owed_rub": int(initial_owed),
        })
    _credit_cards.append(card)
    _cards_by_id[card_id] = card
    _cards_by_client.setdefault(client["id"], []).append(card)
    return card


def _derive_limit(client: dict[str, Any]) -> int:
    """Лимит ~3 месячных дохода, округляем до 10 000 ₽, не меньше 30 000 ₽."""
    income = int(client.get("income_rub", 0))
    return max(30000, int(round(income * 3, -4)))


def _seed_credit_cards() -> None:
    """Выпускаем карту тем, у кого уже есть кредитный продукт, чтобы данные
    были наполнены сразу. Текущая задолженность зависит от риск-скора."""
    for c in _clients:
        prods = c.get("products") or []
        if not any(p in CREDIT_PRODUCTS for p in prods):
            continue
        limit = _derive_limit(c)
        util = min(0.9, max(0.0, float(c.get("risk_score", 0.3))))
        owed = min(limit, int(round(limit * util, -2)))
        _issue_card(c, limit, c.get("joined_at", "2023-01-01"), owed)


_seed_credit_cards()

app = FastAPI(title="backend — ядро данных", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "team": TEAM_NAME, "block": "backend",
            "commit": COMMIT, "clients_loaded": len(_clients),
            "transactions_loaded": len(_transactions),
            "credit_cards_loaded": len(_credit_cards)}


@app.get("/clients")
async def list_clients(
    segment: str | None = Query(default=None),
    has_overdue: bool | None = None,
    min_income: int | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    out = _clients
    if segment:
        out = [c for c in out if c.get("segment") == segment]
    if has_overdue is not None:
        out = [c for c in out if bool(c.get("has_overdue_history")) == has_overdue]
    if min_income is not None:
        out = [c for c in out if c.get("income_rub", 0) >= min_income]
    return {"total": len(out), "items": out[:limit]}


@app.get("/clients/{client_id}")
async def get_client(client_id: str) -> dict:
    c = _clients_by_id.get(client_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    return c


@app.get("/transactions/{client_id}")
async def get_transactions(
    client_id: str, limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    if client_id not in _clients_by_id:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    txs = [t for t in _transactions if t["client_id"] == client_id]
    txs.sort(key=lambda t: t["ts"], reverse=True)
    return {"total": len(txs), "items": txs[:limit]}


@app.post("/api/transfer")
async def api_transfer(payload: dict) -> dict:
    from_id = payload.get("from_client_id")
    to_query = (payload.get("to") or "").strip()
    amount = int(payload.get("amount_rub") or 0)
    if from_id not in _clients_by_id:
        raise HTTPException(status_code=404, detail="отправитель не найден")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="укажи положительную сумму")
    if not to_query:
        raise HTTPException(status_code=400, detail="укажи получателя")
    sender = _clients_by_id[from_id]
    if amount > sender["balance_rub"]:
        raise HTTPException(
            status_code=400,
            detail=f"недостаточно средств: на счёте {sender['balance_rub']} ₽",
        )
    receiver: dict[str, Any] | None = None
    if to_query in _clients_by_id and to_query != from_id:
        receiver = _clients_by_id[to_query]
    else:
        tql = to_query.lower()
        for c in _clients:
            if c["id"] != from_id and (tql == c["name"].lower() or tql in c["name"].lower()):
                receiver = c
                break
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    sender["balance_rub"] -= amount
    out_tx = {
        "id": f"t-{100000 + len(_transactions) + 1:08d}",
        "client_id": from_id, "type": "transfer_out", "amount_rub": -amount,
        "ts": now_iso, "counterparty": receiver["name"] if receiver else to_query,
        "cashback_rub": 0,
    }
    _transactions.append(out_tx)
    if receiver:
        receiver["balance_rub"] += amount
        _transactions.append({
            "id": f"t-{100000 + len(_transactions) + 1:08d}",
            "client_id": receiver["id"], "type": "transfer_in", "amount_rub": amount,
            "ts": now_iso, "counterparty": sender["name"], "cashback_rub": 0,
        })
        kind, label = "internal", receiver["name"]
    else:
        kind, label = "external", to_query
    return {
        "status": "ok", "kind": kind, "amount_rub": amount, "to": label,
        "from_client_id": from_id, "new_balance_rub": sender["balance_rub"],
        "tx_id": out_tx["id"], "ts": now_iso,
    }


@app.get("/cashback/{client_id}")
async def get_cashback(client_id: str) -> dict:
    c = _clients_by_id.get(client_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    return {
        "client_id": client_id,
        "cashback_balance_rub": int(c.get("cashback_balance_rub", 0)),
        "cashback_rate": CASHBACK_RATE,
    }


@app.post("/api/purchase")
async def api_purchase(payload: dict) -> dict:
    """Покупка клиента: списываем сумму с баланса и начисляем кешбэк."""
    cid = payload.get("client_id")
    amount = int(payload.get("amount_rub") or 0)
    merchant = (payload.get("merchant") or "магазин").strip()
    c = _clients_by_id.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="клиент не найден")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="укажи положительную сумму")
    if amount > c["balance_rub"]:
        raise HTTPException(
            status_code=400,
            detail=f"недостаточно средств: на счёте {c['balance_rub']} ₽",
        )
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    c["balance_rub"] -= amount
    earned = int(amount * CASHBACK_RATE)
    c["cashback_balance_rub"] = int(c.get("cashback_balance_rub", 0)) + earned
    tx = {
        "id": f"t-{100000 + len(_transactions) + 1:08d}",
        "client_id": cid, "type": "purchase", "amount_rub": -amount,
        "ts": now_iso, "counterparty": merchant, "cashback_rub": earned,
    }
    _transactions.append(tx)
    return {
        "status": "ok", "client_id": cid, "amount_rub": amount, "merchant": merchant,
        "cashback_earned_rub": earned,
        "new_balance_rub": c["balance_rub"],
        "cashback_balance_rub": c["cashback_balance_rub"],
        "tx_id": tx["id"], "ts": now_iso,
    }


@app.post("/api/cashback/redeem")
async def api_cashback_redeem(payload: dict) -> dict:
    """Списываем кешбэк клиента и зачисляем эту сумму на его обычный баланс."""
    cid = payload.get("client_id")
    amount = int(payload.get("amount_rub") or 0)
    c = _clients_by_id.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="клиент не найден")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="укажи положительную сумму")
    cashback = int(c.get("cashback_balance_rub", 0))
    if amount > cashback:
        raise HTTPException(
            status_code=400,
            detail=f"недостаточно кешбэка: доступно {cashback} ₽",
        )
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    c["cashback_balance_rub"] = cashback - amount
    c["balance_rub"] += amount
    tx = {
        "id": f"t-{100000 + len(_transactions) + 1:08d}",
        "client_id": cid, "type": "cashback_redeem", "amount_rub": amount,
        "ts": now_iso, "counterparty": "кешбэк", "cashback_rub": 0,
    }
    _transactions.append(tx)
    return {
        "status": "ok", "client_id": cid, "redeemed_rub": amount,
        "new_balance_rub": c["balance_rub"],
        "cashback_balance_rub": c["cashback_balance_rub"],
        "tx_id": tx["id"], "ts": now_iso,
    }


# ---------- Кредитные карты ----------

@app.get("/credit-cards")
async def list_credit_cards(
    client_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    cards = _credit_cards
    if client_id:
        cards = _cards_by_client.get(client_id, [])
    if status:
        cards = [c for c in cards if c["status"] == status]
    return {"total": len(cards), "items": [_card_view(c) for c in cards[:limit]]}


@app.get("/clients/{client_id}/credit-cards")
async def client_credit_cards(client_id: str) -> dict:
    if client_id not in _clients_by_id:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    cards = _cards_by_client.get(client_id, [])
    return {"total": len(cards), "items": [_card_view(c) for c in cards]}


@app.get("/credit-cards/{card_id}")
async def get_credit_card(card_id: str) -> dict:
    card = _cards_by_id.get(card_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"карта {card_id} не найдена")
    return _card_view(card, with_history=True)


@app.get("/credit-cards/{card_id}/history")
async def credit_card_history(
    card_id: str, limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    card = _cards_by_id.get(card_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"карта {card_id} не найдена")
    items = list(reversed(card["history"]))[:limit]
    return {"total": len(card["history"]), "items": items}


@app.post("/api/credit-cards")
async def open_credit_card(payload: dict) -> dict:
    """Выпуск новой кредитной карты клиенту. Лимит можно задать явно
    (`credit_limit_rub`) или оставить пустым — посчитаем от дохода."""
    cid = payload.get("client_id")
    client = _clients_by_id.get(cid)
    if not client:
        raise HTTPException(status_code=404, detail="клиент не найден")
    limit = payload.get("credit_limit_rub")
    limit = int(limit) if limit else _derive_limit(client)
    if limit <= 0:
        raise HTTPException(status_code=400, detail="лимит должен быть положительным")
    opened = datetime.now().date().isoformat()
    card = _issue_card(client, limit, opened, initial_owed=0)
    return {"status": "ok", **_card_view(card, with_history=True)}


@app.post("/api/credit-cards/{card_id}/charge")
async def charge_credit_card(card_id: str, payload: dict) -> dict:
    """Покупка по кредитной карте: увеличивает долг, уменьшает доступный лимит."""
    card = _cards_by_id.get(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="карта не найдена")
    if card["status"] != "active":
        raise HTTPException(status_code=400, detail=f"карта {card['status']}, операция недоступна")
    amount = int(payload.get("amount_rub") or 0)
    merchant = (payload.get("merchant") or "магазин").strip()
    if amount <= 0:
        raise HTTPException(status_code=400, detail="укажи положительную сумму")
    available = card["credit_limit_rub"] - card["balance_owed_rub"]
    if amount > available:
        raise HTTPException(
            status_code=400,
            detail=f"превышен лимит: доступно {available} ₽",
        )
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    card["balance_owed_rub"] += amount
    card["history"].append({
        "ts": now_iso, "type": "charge", "amount_rub": amount,
        "counterparty": merchant, "balance_owed_rub": card["balance_owed_rub"],
    })
    return {"status": "ok", "card_id": card_id, "charged_rub": amount,
            "merchant": merchant, **_card_view(card)}


@app.post("/api/credit-cards/{card_id}/payment")
async def pay_credit_card(card_id: str, payload: dict) -> dict:
    """Платёж по карте: уменьшает долг, возвращает доступный лимит."""
    card = _cards_by_id.get(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="карта не найдена")
    amount = int(payload.get("amount_rub") or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="укажи положительную сумму")
    owed = card["balance_owed_rub"]
    if amount > owed:
        raise HTTPException(
            status_code=400,
            detail=f"платёж больше долга: к оплате всего {owed} ₽",
        )
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    card["balance_owed_rub"] -= amount
    card["history"].append({
        "ts": now_iso, "type": "payment", "amount_rub": amount,
        "balance_owed_rub": card["balance_owed_rub"],
    })
    return {"status": "ok", "card_id": card_id, "paid_rub": amount,
            **_card_view(card)}


# ---------- Продукты клиента ----------

@app.post("/clients/{client_id}/products")
@app.post("/api/clients/{client_id}/products")
async def add_client_product(client_id: str, payload: dict) -> dict:
    """Записать новый продукт в профиль клиента. Зовёт cib после того, как
    подтвердил открытие (вклад, карта и т.п.). Принимает JSON
    `{product, opened_at?, source?, details?}`. `product` — код продукта
    (строка). Возвращает `{status, client_id, product, products, event}`.
    404 — если клиента нет, 400 — если не указан продукт."""
    client = _clients_by_id.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    product = (payload.get("product") or "").strip()
    if not product:
        raise HTTPException(status_code=400, detail="укажи продукт (поле product)")
    opened_at = (payload.get("opened_at") or "").strip() \
        or datetime.now().date().isoformat()
    source = (payload.get("source") or "cib").strip()
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    now_iso = datetime.now().replace(microsecond=0).isoformat()

    products = client.setdefault("products", [])
    already_had = product in products
    if not already_had:
        products.append(product)

    event = {
        "event_id": f"pe-{len(_product_events) + 1:06d}",
        "client_id": client_id,
        "product": product,
        "opened_at": opened_at,
        "source": source,
        "details": details,
        "ts": now_iso,
    }
    _product_events.append(event)
    _product_events_by_client.setdefault(client_id, []).append(event)

    return {
        "status": "ok",
        "client_id": client_id,
        "product": product,
        "already_had": already_had,
        "products": products,
        "event": event,
    }


@app.get("/clients/{client_id}/products")
async def list_client_products(client_id: str) -> dict:
    """Продукты клиента и журнал их открытий (новые сверху)."""
    client = _clients_by_id.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    events = list(reversed(_product_events_by_client.get(client_id, [])))
    return {
        "client_id": client_id,
        "products": client.get("products", []),
        "events_total": len(events),
        "events": events,
    }


# ---------- Вклады: движение денег ----------

def _add_months(iso_date: str, months: int) -> str:
    """Прибавить months месяцев к дате YYYY-MM-DD, аккуратно к концу месяца."""
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    total = (d.year * 12 + (d.month - 1)) + int(months)
    year, month = divmod(total, 12)
    month += 1
    # последний допустимый день целевого месяца
    if month == 12:
        last = 31
    else:
        nxt = datetime(year + (1 if month == 12 else 0),
                       (month % 12) + 1, 1).date()
        last = (nxt - timedelta(days=1)).day
    day = min(d.day, last)
    return datetime(year, month, day).date().isoformat()


def _deposit_view(dep: dict[str, Any]) -> dict[str, Any]:
    return {
        "deposit_id": dep["deposit_id"],
        "client_id": dep["client_id"],
        "product": dep["product"],
        "amount_rub": dep["amount_rub"],
        "term_months": dep["term_months"],
        "rate_pct": dep["rate_pct"],
        "status": dep["status"],
        "opened_at": dep["opened_at"],
        "matures_at": dep["matures_at"],
    }


@app.post("/api/deposits")
async def open_deposit(payload: dict) -> dict:
    """Открыть вклад: списываем `amount_rub` со счёта клиента и держим во
    вкладе. Кешбэк не начисляется. Принимает JSON
    `{client_id, product, amount_rub, term_months?, rate_pct?}`. Возвращает
    `{status, client_id, deposit_id, product, amount_rub, new_balance_rub,
    matures_at, ts}`. `400`, если сумма больше баланса; `404`, если клиента нет."""
    cid = payload.get("client_id")
    client = _clients_by_id.get(cid)
    if not client:
        raise HTTPException(status_code=404, detail="клиент не найден")
    product = (payload.get("product") or "deposit").strip()
    amount = int(payload.get("amount_rub") or 0)
    term_months = int(payload.get("term_months") or 0)
    rate_pct = float(payload.get("rate_pct") or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="укажи положительную сумму")
    if amount > client["balance_rub"]:
        raise HTTPException(
            status_code=400,
            detail=f"недостаточно средств: на счёте {client['balance_rub']} ₽",
        )
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    opened_at = datetime.now().date().isoformat()
    matures_at = _add_months(opened_at, term_months) if term_months > 0 else opened_at
    client["balance_rub"] -= amount

    deposit_id = f"d-{len(_deposits) + 1:06d}"
    early_withdrawal = product in DEPOSIT_FLEX_PRODUCTS
    dep = {
        "deposit_id": deposit_id,
        "client_id": cid,
        "product": product,
        "amount_rub": amount,
        "term_months": term_months,
        "rate_pct": rate_pct,
        "early_withdrawal": early_withdrawal,
        "status": "active",
        "opened_at": opened_at,
        "matures_at": matures_at,
        "ts": now_iso,
    }
    _deposits.append(dep)
    _deposits_by_id[deposit_id] = dep
    _deposits_by_client.setdefault(cid, []).append(dep)

    tx = {
        "id": f"t-{100000 + len(_transactions) + 1:08d}",
        "client_id": cid, "type": "deposit_open", "amount_rub": -amount,
        "ts": now_iso, "counterparty": product, "cashback_rub": 0,
    }
    _transactions.append(tx)

    return {
        "status": "ok",
        "client_id": cid,
        "deposit_id": deposit_id,
        "product": product,
        "amount_rub": amount,
        "new_balance_rub": client["balance_rub"],
        "matures_at": matures_at,
        "ts": now_iso,
    }


@app.get("/clients/{client_id}/deposits")
async def list_client_deposits(client_id: str) -> dict:
    """Вклады клиента (новые сверху)."""
    if client_id not in _clients_by_id:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    deps = list(reversed(_deposits_by_client.get(client_id, [])))
    return {"client_id": client_id, "total": len(deps),
            "items": [_deposit_view(d) for d in deps]}


@app.get("/deposits/{deposit_id}")
async def get_deposit(deposit_id: str) -> dict:
    dep = _deposits_by_id.get(deposit_id)
    if not dep:
        raise HTTPException(status_code=404, detail=f"вклад {deposit_id} не найден")
    return _deposit_view(dep)


@app.post("/api/deposits/{deposit_id}/withdraw")
async def withdraw_deposit(deposit_id: str, payload: dict | None = None) -> dict:
    """Закрыть вклад и вернуть тело (+ проценты, если срок вышел) на счёт.
    Тело `{}` или `{early: true}`. Для гибких вкладов снятие всегда без потери
    процентов; для срочных досрочное снятие платит сниженные проценты.
    Возвращает `{status, client_id, returned_rub, new_balance_rub, ts}`."""
    payload = payload or {}
    dep = _deposits_by_id.get(deposit_id)
    if not dep:
        raise HTTPException(status_code=404, detail=f"вклад {deposit_id} не найден")
    if dep["status"] != "active":
        raise HTTPException(status_code=400, detail=f"вклад уже {dep['status']}")
    client = _clients_by_id.get(dep["client_id"])
    if not client:
        raise HTTPException(status_code=404, detail="клиент не найден")

    now_iso = datetime.now().replace(microsecond=0).isoformat()
    today = datetime.now().date().isoformat()
    principal = int(dep["amount_rub"])
    # Полные проценты за весь срок.
    full_interest = int(round(
        principal * (dep["rate_pct"] / 100.0) * (dep["term_months"] / 12.0)))
    matured = today >= dep["matures_at"]
    early_requested = bool(payload.get("early"))

    if matured and not early_requested:
        interest = full_interest
        kind = "matured"
    elif dep["early_withdrawal"]:
        # Гибкий вклад — досрочное снятие без потери процентов.
        interest = full_interest
        kind = "flex"
    else:
        # Срочный вклад досрочно — сниженные проценты (треть от начисленных).
        interest = int(round(full_interest * 0.3))
        kind = "early"

    returned = principal + interest
    client["balance_rub"] += returned
    dep["status"] = "closed"
    dep["closed_at"] = now_iso
    dep["returned_rub"] = returned

    tx = {
        "id": f"t-{100000 + len(_transactions) + 1:08d}",
        "client_id": dep["client_id"], "type": "deposit_withdraw",
        "amount_rub": returned, "ts": now_iso, "counterparty": dep["product"],
        "cashback_rub": 0,
    }
    _transactions.append(tx)

    return {
        "status": "ok",
        "client_id": dep["client_id"],
        "deposit_id": deposit_id,
        "kind": kind,
        "principal_rub": principal,
        "interest_rub": interest,
        "returned_rub": returned,
        "new_balance_rub": client["balance_rub"],
        "ts": now_iso,
    }


# ---------- Инвестиции: портфель и заявки ----------

@app.get("/instruments")
async def list_instruments() -> dict:
    """Каталог доступных инструментов с текущей ценой."""
    items = list(_instruments.values())
    return {"total": len(items), "items": items}


def _portfolio_view(client_id: str) -> dict:
    """Собрать портфель клиента: позиции с текущей стоимостью и P/L."""
    holdings = _holdings_by_client.get(client_id, {})
    positions = []
    market_value = 0
    cost_basis = 0
    for h in holdings.values():
        instr = _instruments.get(h["symbol"], {})
        price = int(instr.get("price_rub", 0))
        qty = int(h["qty"])
        value = price * qty
        cost = int(h["avg_cost_rub"]) * qty
        market_value += value
        cost_basis += cost
        positions.append({
            "symbol": h["symbol"],
            "name": instr.get("name", h["symbol"]),
            "qty": qty,
            "avg_cost_rub": int(h["avg_cost_rub"]),
            "current_price_rub": price,
            "market_value_rub": value,
            "cost_basis_rub": cost,
            "unrealized_pnl_rub": value - cost,
        })
    positions.sort(key=lambda p: p["market_value_rub"], reverse=True)
    return {
        "client_id": client_id,
        "positions": positions,
        "market_value_rub": market_value,
        "cost_basis_rub": cost_basis,
        "unrealized_pnl_rub": market_value - cost_basis,
    }


@app.get("/investments/summary")
async def investments_summary() -> dict:
    """Сводка по всему банку: активы под управлением (AUM) по всем клиентам,
    суммарная стоимость, вложено, прибыль/убыток, число инвесторов и разбивка
    по инструментам."""
    total_value = 0
    total_cost = 0
    investors = 0
    by_instrument: dict[str, dict[str, Any]] = {}
    for client_id, holdings in _holdings_by_client.items():
        if not holdings:
            continue
        investors += 1
        for h in holdings.values():
            instr = _instruments.get(h["symbol"], {})
            price = int(instr.get("price_rub", 0))
            qty = int(h["qty"])
            value = price * qty
            cost = int(h["avg_cost_rub"]) * qty
            total_value += value
            total_cost += cost
            row = by_instrument.setdefault(h["symbol"], {
                "symbol": h["symbol"],
                "name": instr.get("name", h["symbol"]),
                "qty": 0, "market_value_rub": 0, "holders": 0,
            })
            row["qty"] += qty
            row["market_value_rub"] += value
            row["holders"] += 1
    breakdown = sorted(by_instrument.values(),
                       key=lambda r: r["market_value_rub"], reverse=True)
    return {
        "assets_under_management_rub": total_value,
        "invested_rub": total_cost,
        "unrealized_pnl_rub": total_value - total_cost,
        "investors": investors,
        "orders_total": len(_orders),
        "by_instrument": breakdown,
    }


@app.get("/clients/{client_id}/portfolio")
async def get_portfolio(client_id: str) -> dict:
    """Инвестиционный портфель клиента: позиции, текущая стоимость, прибыль/убыток."""
    if client_id not in _clients_by_id:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    return _portfolio_view(client_id)


def _process_order(client_id: str, payload: dict) -> dict:
    """Обработать заявку buy/sell. buy — списывает деньги со счёта и
    добавляет бумаги; sell — продаёт бумаги и зачисляет деньги на счёт."""
    client = _clients_by_id.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    side = (payload.get("side") or "").strip().lower()
    if side not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="side должен быть buy или sell")
    symbol = (payload.get("symbol") or "").strip().upper()
    instr = _instruments.get(symbol)
    if not instr:
        raise HTTPException(status_code=400, detail=f"инструмент {symbol} не найден")
    qty = int(payload.get("qty") or 0)
    if qty <= 0:
        raise HTTPException(status_code=400, detail="qty должен быть положительным")

    price = int(instr["price_rub"])
    gross = price * qty
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    holdings = _holdings_by_client.setdefault(client_id, {})

    if side == "buy":
        if gross > client["balance_rub"]:
            raise HTTPException(
                status_code=400,
                detail=f"недостаточно средств: нужно {gross} ₽, на счёте {client['balance_rub']} ₽",
            )
        client["balance_rub"] -= gross
        pos = holdings.get(symbol)
        if pos:
            total_qty = pos["qty"] + qty
            pos["avg_cost_rub"] = int(
                round((pos["avg_cost_rub"] * pos["qty"] + price * qty) / total_qty))
            pos["qty"] = total_qty
        else:
            holdings[symbol] = {"symbol": symbol, "qty": qty, "avg_cost_rub": price}
        tx_type = "invest_buy"
        amount_signed = -gross
    else:  # sell
        pos = holdings.get(symbol)
        if not pos or pos["qty"] < qty:
            have = pos["qty"] if pos else 0
            raise HTTPException(
                status_code=400,
                detail=f"недостаточно бумаг {symbol}: есть {have}, продаёте {qty}",
            )
        client["balance_rub"] += gross
        pos["qty"] -= qty
        if pos["qty"] == 0:
            del holdings[symbol]
        tx_type = "invest_sell"
        amount_signed = gross

    tx = {
        "id": f"t-{100000 + len(_transactions) + 1:08d}",
        "client_id": client_id, "type": tx_type, "amount_rub": amount_signed,
        "ts": now_iso, "counterparty": symbol, "cashback_rub": 0,
    }
    _transactions.append(tx)

    order = {
        "order_id": f"ord-{len(_orders) + 1:06d}",
        "client_id": client_id, "side": side, "symbol": symbol, "qty": qty,
        "price_rub": price, "gross_rub": gross, "ts": now_iso, "tx_id": tx["id"],
    }
    _orders.append(order)
    _orders_by_client.setdefault(client_id, []).append(order)

    return {
        "status": "ok",
        "order": order,
        "new_balance_rub": client["balance_rub"],
        "portfolio": _portfolio_view(client_id),
    }


@app.post("/clients/{client_id}/orders")
@app.post("/api/clients/{client_id}/orders")
async def place_order(client_id: str, payload: dict) -> dict:
    """Заявка на покупку/продажу инструмента. JSON `{side, symbol, qty}`,
    где side = buy|sell. Возвращает `{status, order, new_balance_rub, portfolio}`."""
    return _process_order(client_id, payload)


@app.get("/clients/{client_id}/orders")
async def list_orders(
    client_id: str, limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    """История заявок клиента, новые сверху."""
    if client_id not in _clients_by_id:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    items = list(reversed(_orders_by_client.get(client_id, [])))[:limit]
    return {"total": len(_orders_by_client.get(client_id, [])), "items": items}


# ---------- Рекомендации: какой продукт предложить клиенту (next best offer) ----------
#
# Аналитический инструмент: смотрим на данные клиента (доход, остаток на счёте,
# текущие продукты, риск-скор, просрочки, сегмент, возраст) и предлагаем те
# продукты, которых у него ещё нет и которые ему, вероятно, подойдут. У каждой
# рекомендации — оценка уместности (score 0..1), причина простыми словами и,
# где уместно, ожидаемая выгода. Пороги вынесены в константы, чтобы их легко
# было крутить под продуктовую политику.

# Депозитная ставка для оценки выгоды в рекомендации (годовых).
RECO_DEPOSIT_RATE = 0.17
# Остаток, выше которого деньги считаем «лежащими без дела» (кандидат на вклад).
RECO_DEPOSIT_MIN_BALANCE = 100000
# Остаток для гибкого накопительного счёта (порог ниже, чем у вклада).
RECO_SAVINGS_MIN_BALANCE = 30000
# Минимальный доход и максимальный риск для кредитных предложений.
RECO_CARD_MIN_INCOME = 40000
RECO_CARD_MAX_RISK = 0.5
RECO_LOAN_MIN_INCOME = 50000
RECO_LOAN_MAX_RISK = 0.4
RECO_MORTGAGE_MIN_INCOME = 80000
# Остаток/доход, при которых mass-клиенту предлагаем апгрейд до premium.
RECO_PREMIUM_MIN_INCOME = 120000
RECO_PREMIUM_MIN_BALANCE = 500000
# Остаток, при котором клиенту без портфеля предлагаем инвестиции.
RECO_INVEST_MIN_BALANCE = 150000
_RECO_AFFLUENT = {"mass_affluent", "premium", "private", "sme"}


def _client_state(c: dict[str, Any]) -> dict[str, Any]:
    """Сводим всё, что знаем о клиенте, в один словарь для правил."""
    cid = c["id"]
    products = set(c.get("products") or [])
    deps = _deposits_by_client.get(cid, [])
    return {
        "products": products,
        "balance": int(c.get("balance_rub", 0)),
        "income": int(c.get("income_rub", 0)),
        "risk": float(c.get("risk_score", 0.5)),
        "overdue": bool(c.get("has_overdue_history")),
        "segment": c.get("segment"),
        "age": int(c.get("age", 0)),
        "has_active_deposit": any(d["status"] == "active" for d in deps)
        or "deposit" in products,
        "has_portfolio": bool(_holdings_by_client.get(cid)),
        "has_card": bool(_cards_by_client.get(cid)) or "credit_card" in products,
        "cashback": int(c.get("cashback_balance_rub", 0)),
    }


def _recommend_for_client(c: dict[str, Any]) -> list[dict[str, Any]]:
    """Список продуктовых предложений для одного клиента, сильнейшие сверху."""
    s = _client_state(c)
    recs: list[dict[str, Any]] = []

    # 1. Срочный вклад — много свободных денег лежит без дела.
    if not s["has_active_deposit"] and s["balance"] >= RECO_DEPOSIT_MIN_BALANCE:
        amount = int(round(s["balance"] * 0.6, -3))
        benefit = int(amount * RECO_DEPOSIT_RATE)
        recs.append({
            "product": "deposit-12m",
            "title": "Срочный вклад на 12 месяцев",
            "reason": f"на счёте лежит {s['balance']} ₽ почти без дохода — "
                      f"вклад под {int(RECO_DEPOSIT_RATE * 100)}% принесёт "
                      f"около {benefit} ₽ в год",
            "score": round(min(1.0, s["balance"] / 500000), 2),
            "suggested_amount_rub": amount,
            "est_annual_benefit_rub": benefit,
        })
    # 2. Гибкий накопительный счёт — денег поменьше, но тоже лежат.
    elif not s["has_active_deposit"] and s["balance"] >= RECO_SAVINGS_MIN_BALANCE \
            and "savings" not in s["products"]:
        recs.append({
            "product": "deposit-flex",
            "title": "Гибкий накопительный счёт",
            "reason": f"{s['balance']} ₽ можно отложить с процентом и снимать "
                      f"в любой момент без потерь",
            "score": round(min(0.7, s["balance"] / 300000), 2),
            "suggested_amount_rub": int(round(s["balance"] * 0.4, -3)),
        })

    # 3. Кредитная карта — нет карты, доход стабильный, без просрочек.
    if not s["has_card"] and not s["overdue"] \
            and s["income"] >= RECO_CARD_MIN_INCOME and s["risk"] <= RECO_CARD_MAX_RISK:
        limit = _derive_limit(c)
        recs.append({
            "product": "credit_card",
            "title": "Кредитная карта",
            "reason": f"доход {s['income']} ₽/мес и чистая история — "
                      f"одобрим лимит около {limit} ₽",
            "score": round(min(1.0, (1 - s["risk"]) * (s["income"] / 100000)), 2),
            "suggested_limit_rub": limit,
        })

    # 4. Инвестиции — есть свободные деньги, но нет портфеля.
    if not s["has_portfolio"] and s["balance"] >= RECO_INVEST_MIN_BALANCE \
            and s["segment"] in _RECO_AFFLUENT:
        recs.append({
            "product": "investments",
            "title": "Инвестиционный портфель",
            "reason": f"{s['balance']} ₽ свободных средств можно вложить в "
                      f"облигации и фонды и обогнать инфляцию",
            "score": round(min(0.9, s["balance"] / 600000), 2),
        })

    # 5. Потребительский кредит — доход есть, риск низкий, продукта нет.
    if "consumer_credit" not in s["products"] and not s["overdue"] \
            and s["income"] >= RECO_LOAN_MIN_INCOME and s["risk"] <= RECO_LOAN_MAX_RISK:
        recs.append({
            "product": "consumer_credit",
            "title": "Потребительский кредит",
            "reason": f"стабильный доход {s['income']} ₽/мес и низкий риск — "
                      f"быстрое одобрение",
            "score": round(min(0.8, (1 - s["risk"]) * (s["income"] / 120000)), 2),
        })

    # 6. Ипотека — высокий доход, без просрочек, affluent-сегмент.
    if "mortgage" not in s["products"] and not s["overdue"] \
            and s["income"] >= RECO_MORTGAGE_MIN_INCOME \
            and s["segment"] in _RECO_AFFLUENT and s["age"] <= 60:
        recs.append({
            "product": "mortgage",
            "title": "Ипотека",
            "reason": f"доход {s['income']} ₽/мес позволяет обслуживать "
                      f"ипотеку — подберём программу",
            "score": round(min(0.85, s["income"] / 250000), 2),
        })

    # 7. Апгрейд до premium — mass-клиент с премиальными деньгами/доходом.
    if s["segment"] == "mass" \
            and (s["income"] >= RECO_PREMIUM_MIN_INCOME
                 or s["balance"] >= RECO_PREMIUM_MIN_BALANCE):
        recs.append({
            "product": "premium_upgrade",
            "title": "Перевод в премиальный сегмент",
            "reason": "доход и остатки уже премиального уровня — "
                      "персональный менеджер и улучшенные условия",
            "score": 0.6,
        })

    # 8. Потратить накопленный кешбэк — крупный неиспользованный баланс.
    if s["cashback"] >= 3000:
        recs.append({
            "product": "cashback_redeem",
            "title": "Потратить накопленный кешбэк",
            "reason": f"накоплено {s['cashback']} ₽ кешбэка — можно зачислить "
                      f"на счёт прямо сейчас",
            "score": 0.4,
            "available_cashback_rub": s["cashback"],
        })

    recs.sort(key=lambda r: r["score"], reverse=True)
    return recs


@app.get("/clients/{client_id}/recommendations")
async def client_recommendations(
    client_id: str, limit: int = Query(default=5, ge=1, le=20),
) -> dict:
    """Продуктовые предложения для клиента на основе его данных, сильнейшие
    сверху. Возвращает `{client_id, name, segment, recommendations: [...]}`.
    Рекомендация — `{product, title, reason, score, ...доп. поля}`."""
    c = _clients_by_id.get(client_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    recs = _recommend_for_client(c)[:limit]
    return {
        "client_id": client_id,
        "name": c.get("name"),
        "segment": c.get("segment"),
        "recommendations": recs,
    }


@app.get("/recommendations/summary")
async def recommendations_summary(
    segment: str | None = Query(default=None),
) -> dict:
    """Сводка по всему банку: для каждого продукта — скольким клиентам его
    стоит предложить и какой суммарный потенциал (где считается). Помогает
    решить, какую фичу продвигать. Параметр `segment` — посчитать только по
    одному сегменту. Возвращает `{clients_analysed, by_product: [...]}`."""
    by_product: dict[str, dict[str, Any]] = {}
    analysed = 0
    for c in _clients:
        if segment and c.get("segment") != segment:
            continue
        analysed += 1
        for r in _recommend_for_client(c):
            row = by_product.setdefault(r["product"], {
                "product": r["product"],
                "title": r["title"],
                "candidates": 0,
                "potential_amount_rub": 0,
                "potential_annual_benefit_rub": 0,
            })
            row["candidates"] += 1
            row["potential_amount_rub"] += int(r.get("suggested_amount_rub", 0))
            row["potential_annual_benefit_rub"] += int(
                r.get("est_annual_benefit_rub", 0))
    breakdown = sorted(by_product.values(),
                       key=lambda r: r["candidates"], reverse=True)
    return {"clients_analysed": analysed, "by_product": breakdown}


# ---------- Аналитика: какие фичи приводят клиентов ----------
#
# Честная оговорка: в данных нет поля «клиент пришёл ради этой фичи». Есть дата
# прихода (`joined_at`) и продукты, которыми клиент владеет сейчас. Поэтому
# смотрим с двух сторон: (1) по существующей базе — у скольких клиентов есть
# каждая фича, какую ценность (остатки, доход) они приносят и в какие годы эти
# клиенты пришли; (2) по «живому» журналу — что реально оформляют прямо сейчас
# через новые ручки (вклады, карты, инвестиции, журнал продуктов). Второе и есть
# настоящая атрибуция новых подключений — она копится с момента запуска фич.

# Понятные названия фич для отчёта.
_FEATURE_TITLES = {
    "deposit": "Вклады", "savings": "Накопительный счёт",
    "credit_card": "Кредитная карта", "consumer_credit": "Потребкредит",
    "auto_credit": "Автокредит", "mortgage": "Ипотека", "debit": "Дебетовая карта",
}


@app.get("/analytics/feature-acquisition")
async def feature_acquisition() -> dict:
    """Какие фичи приводят и держат клиентов. Возвращает `{clients_total,
    by_feature: [...], acquisition_by_year: {...}, live_adoption: {...}, note}`.
    `by_feature` (сильнейшие сверху) — `{feature, title, clients, share_pct,
    total_balance_rub, avg_balance_rub, avg_income_rub, joined_by_year}`.
    `live_adoption` — что реально оформляют через новые ручки с момента запуска."""
    total = len(_clients)
    by_feature: dict[str, dict[str, Any]] = {}
    acquisition_by_year: dict[str, int] = {}

    for c in _clients:
        year = (c.get("joined_at") or "")[:4] or "?"
        acquisition_by_year[year] = acquisition_by_year.get(year, 0) + 1
        balance = int(c.get("balance_rub", 0))
        income = int(c.get("income_rub", 0))
        for p in c.get("products") or []:
            row = by_feature.setdefault(p, {
                "feature": p,
                "title": _FEATURE_TITLES.get(p, p),
                "clients": 0,
                "total_balance_rub": 0,
                "_income_sum": 0,
                "joined_by_year": {},
            })
            row["clients"] += 1
            row["total_balance_rub"] += balance
            row["_income_sum"] += income
            row["joined_by_year"][year] = row["joined_by_year"].get(year, 0) + 1

    feats = []
    for row in by_feature.values():
        n = row["clients"]
        row["share_pct"] = round(100 * n / total, 1) if total else 0
        row["avg_balance_rub"] = int(row["total_balance_rub"] / n) if n else 0
        row["avg_income_rub"] = int(row.pop("_income_sum") / n) if n else 0
        row["joined_by_year"] = dict(sorted(row["joined_by_year"].items()))
        feats.append(row)
    feats.sort(key=lambda r: r["clients"], reverse=True)

    # Живая атрибуция: что оформляют через новые ручки прямо сейчас.
    openings_by_product: dict[str, int] = {}
    for e in _product_events:
        openings_by_product[e["product"]] = openings_by_product.get(e["product"], 0) + 1
    live_adoption = {
        "deposits_opened": len(_deposits),
        "credit_cards_issued_via_api": sum(
            1 for c in _credit_cards if not c["history"]
            or c["history"][0].get("note") != "перенос текущей задолженности"),
        "investment_accounts_opened": sum(
            1 for h in _holdings_by_client.values() if h),
        "product_openings_logged": len(_product_events),
        "openings_by_product": dict(sorted(
            openings_by_product.items(), key=lambda kv: kv[1], reverse=True)),
    }

    return {
        "clients_total": total,
        "by_feature": feats,
        "acquisition_by_year": dict(sorted(acquisition_by_year.items())),
        "live_adoption": live_adoption,
        "note": "by_feature и acquisition_by_year — по существующей базе "
                "(чем владеют клиенты и когда пришли); это связь, не доказанная "
                "причина. live_adoption — настоящая атрибуция новых подключений "
                "через новые ручки, копится с момента запуска фич.",
    }
