"""Блок backend — ядро данных банка команды.

Хранит клиентов, транзакции, балансы; отдаёт базовый API. UI нет.
Данные in-memory из seed/*.jsonl. Кредитное хранилище
(POST/GET /credit-applications) добавляет владелец блока в рамках задачи.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
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
_credit_cards: list[dict[str, Any]] = []
_cards_by_id: dict[str, dict[str, Any]] = {}
_cards_by_client: dict[str, list[dict[str, Any]]] = {}


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
