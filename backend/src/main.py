"""Блок backend — ядро данных банка команды.

Хранит клиентов, транзакции, балансы; отдаёт базовый API. UI нет.
Данные in-memory из seed/*.jsonl. Кредитное хранилище
(POST/GET /credit-applications) добавляет владелец блока в рамках задачи.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

TEAM_NAME = os.environ.get("TEAM_NAME", "team")
COMMIT = os.environ.get("RENDER_GIT_COMMIT", "local")


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
_credit_applications: dict[str, dict[str, Any]] = {}

CREDIT_MIN_AMOUNT_RUB = 50_000
CREDIT_MAX_AMOUNT_RUB = 1_500_000
CREDIT_MIN_TERM_MONTHS = 6
CREDIT_MAX_TERM_MONTHS = 60
CREDIT_MIN_RATE_PCT = 14.9
CREDIT_MAX_RATE_PCT = 24.9


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
    _clients.extend(clients)
    _clients_by_id.update({c["id"]: c for c in clients})
    _transactions.extend(_load_jsonl(SEED_DIR / "transactions.jsonl"))


_load_seed()

app = FastAPI(title="backend — ядро данных", version="1.0.0")


def _client_view(client: dict[str, Any]) -> dict[str, Any]:
    """Expose stable credit-profile fields without inventing missing data."""
    view = dict(client)
    view["monthly_income_rub"] = client.get("income_rub")
    view["risk_level"] = None
    view["has_serious_current_overdue"] = None
    view["is_payroll_client"] = None
    joined_at = client.get("joined_at")
    if not joined_at:
        view["is_loyal_client"] = None
    else:
        try:
            joined_date = date.fromisoformat(joined_at)
            today = date.today()
            try:
                loyalty_cutoff = today.replace(year=today.year - 1)
            except ValueError:
                loyalty_cutoff = today.replace(year=today.year - 1, day=28)
            view["is_loyal_client"] = joined_date <= loyalty_cutoff
        except ValueError:
            view["is_loyal_client"] = None
    return view


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "team": TEAM_NAME, "block": "backend",
            "commit": COMMIT, "clients_loaded": len(_clients),
            "transactions_loaded": len(_transactions)}


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
    return {"total": len(out), "items": [_client_view(c) for c in out[:limit]]}


@app.get("/clients/{client_id}")
async def get_client(client_id: str) -> dict:
    c = _clients_by_id.get(client_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    return _client_view(c)


@app.get("/transactions/{client_id}")
async def get_transactions(
    client_id: str, limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    if client_id not in _clients_by_id:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    txs = [t for t in _transactions if t["client_id"] == client_id]
    txs.sort(key=lambda t: t["ts"], reverse=True)
    return {"total": len(txs), "items": txs[:limit]}


def _credit_application_view(application: dict[str, Any]) -> dict[str, Any]:
    return dict(application)


@app.post("/credit-applications")
async def create_credit_application(payload: dict) -> dict:
    client_id = payload.get("client_id")
    if client_id not in _clients_by_id:
        raise HTTPException(status_code=404, detail="клиент не найден")
    try:
        amount_rub = int(payload.get("amount_rub"))
        term_months = int(payload.get("term_months"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="укажи сумму и срок кредита")
    if not CREDIT_MIN_AMOUNT_RUB <= amount_rub <= CREDIT_MAX_AMOUNT_RUB:
        raise HTTPException(
            status_code=400,
            detail=f"сумма должна быть от {CREDIT_MIN_AMOUNT_RUB} до {CREDIT_MAX_AMOUNT_RUB} ₽",
        )
    if not CREDIT_MIN_TERM_MONTHS <= term_months <= CREDIT_MAX_TERM_MONTHS:
        raise HTTPException(
            status_code=400,
            detail=f"срок должен быть от {CREDIT_MIN_TERM_MONTHS} до {CREDIT_MAX_TERM_MONTHS} месяцев",
        )
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    application_id = f"ca-{len(_credit_applications) + 1:06d}"
    application = {
        "id": application_id,
        "client_id": client_id,
        "amount_rub": amount_rub,
        "term_months": term_months,
        "status": "pending",
        "decision": None,
        "reason_code": None,
        "reason": None,
        "approved_amount_rub": None,
        "approved_term_months": None,
        "personal_rate_pct": None,
        "monthly_payment_rub": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    _credit_applications[application_id] = application
    return _credit_application_view(application)


@app.get("/credit-applications/{application_id}")
async def get_credit_application(application_id: str) -> dict:
    application = _credit_applications.get(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="кредитная заявка не найдена")
    return _credit_application_view(application)


@app.patch("/credit-applications/{application_id}/decision")
async def record_credit_decision(application_id: str, payload: dict) -> dict:
    application = _credit_applications.get(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="кредитная заявка не найдена")
    decision = payload.get("decision")
    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="решение должно быть approved или rejected")
    reason_code = (payload.get("reason_code") or "").strip()
    reason = (payload.get("reason") or "").strip()
    if not reason_code or not reason:
        raise HTTPException(status_code=400, detail="укажи код и причину решения")
    approved_fields = {
        "approved_amount_rub": payload.get("approved_amount_rub"),
        "approved_term_months": payload.get("approved_term_months"),
        "personal_rate_pct": payload.get("personal_rate_pct"),
        "monthly_payment_rub": payload.get("monthly_payment_rub"),
    }
    if decision == "approved":
        try:
            approved_fields["approved_amount_rub"] = int(approved_fields["approved_amount_rub"])
            approved_fields["approved_term_months"] = int(approved_fields["approved_term_months"])
            approved_fields["personal_rate_pct"] = float(approved_fields["personal_rate_pct"])
            approved_fields["monthly_payment_rub"] = int(approved_fields["monthly_payment_rub"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="для одобрения нужны параметры кредита")
        if not CREDIT_MIN_AMOUNT_RUB <= approved_fields["approved_amount_rub"] <= application["amount_rub"]:
            raise HTTPException(status_code=400, detail="одобренная сумма вне допустимого диапазона")
        if not CREDIT_MIN_TERM_MONTHS <= approved_fields["approved_term_months"] <= CREDIT_MAX_TERM_MONTHS:
            raise HTTPException(status_code=400, detail="одобренный срок вне допустимого диапазона")
        if not CREDIT_MIN_RATE_PCT <= approved_fields["personal_rate_pct"] <= CREDIT_MAX_RATE_PCT:
            raise HTTPException(status_code=400, detail="персональная ставка вне диапазона продукта")
        if approved_fields["monthly_payment_rub"] <= 0:
            raise HTTPException(status_code=400, detail="ежемесячный платёж должен быть положительным")
    else:
        approved_fields = {field: None for field in approved_fields}
    application.update({
        "status": "decided",
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        **approved_fields,
        "updated_at": datetime.now().replace(microsecond=0).isoformat(),
    })
    return _credit_application_view(application)


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
    }
    _transactions.append(out_tx)
    if receiver:
        receiver["balance_rub"] += amount
        _transactions.append({
            "id": f"t-{100000 + len(_transactions) + 1:08d}",
            "client_id": receiver["id"], "type": "transfer_in", "amount_rub": amount,
            "ts": now_iso, "counterparty": sender["name"],
        })
        kind, label = "internal", receiver["name"]
    else:
        kind, label = "external", to_query
    return {
        "status": "ok", "kind": kind, "amount_rub": amount, "to": label,
        "from_client_id": from_id, "new_balance_rub": sender["balance_rub"],
        "tx_id": out_tx["id"], "ts": now_iso,
    }
