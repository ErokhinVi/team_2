"""
Дорастить стартовую базу банка дополнительными клиентами.

Существующие 500 клиентов (c-01000..c-01499) остаются как есть — этот скрипт
ДОБАВЛЯЕТ ещё N_NEW клиентов с продолжением нумерации (c-01500..), их
транзакции и кредитную историю, и дописывает их в seed/*.jsonl. Логика и
словари — те же, что в make_seed.py, чтобы новые клиенты были неотличимы по
структуре от исходных. Отдельный random seed, чтобы не повторять тех же людей.

Запуск:
    python3 seed/add_customers.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import random

import make_seed as ms  # переиспользуем словари и генераторы

SEED = 4242
N_NEW = 700  # 500 + 700 = 1200 клиентов
OUT = Path(__file__).resolve().parent
TODAY = datetime(2026, 6, 3)


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")


def main() -> None:
    rng = random.Random(SEED)
    clients = _load(OUT / "clients.jsonl")
    txs = _load(OUT / "transactions.jsonl")
    chist = _load(OUT / "credit_history.jsonl")
    start_idx = len(clients)          # 500 -> новые id с c-01500
    tx_start = len(txs)               # продолжаем нумерацию транзакций
    ch_start = len(chist)             # продолжаем нумерацию кредит-истории

    new_clients: list[dict] = []
    for i in range(N_NEW):
        cid = f"c-{start_idx + i + 1000:05d}"
        first, last = ms._client_name(rng)
        seg, income_range, balance_range = ms._pick_segment(rng)
        has_overdue = rng.random() < {"mass": 0.18, "mass_affluent": 0.08,
                                      "premium": 0.04, "private": 0.02,
                                      "sme": 0.12}[seg]
        # часть новых клиентов пришла совсем недавно — видно рост базы
        joined_days_ago = rng.randint(0, 365 * 5)
        new_clients.append({
            "id": cid,
            "first_name": first,
            "last_name": last,
            "name": f"{first} {last}",
            "age": rng.randint(22, 72),
            "segment": seg,
            "income_rub": rng.randint(*income_range),
            "balance_rub": rng.randint(*balance_range),
            "products": ms._pick_products(seg, rng),
            "risk_score": ms._risk_score(seg, has_overdue, rng),
            "has_overdue_history": has_overdue,
            "joined_at": (TODAY - timedelta(days=joined_days_ago)).date().isoformat(),
        })

    # транзакции для новых клиентов (несколько на каждого)
    new_txs: list[dict] = []
    types = ["transfer_out", "transfer_in", "card_purchase", "atm_withdraw",
             "salary", "utility_payment"]
    k = 0
    for c in new_clients:
        for _ in range(rng.randint(3, 10)):
            ttype = rng.choice(types)
            if ttype == "salary":
                amount, sign = c["income_rub"], 1
            elif ttype == "transfer_in":
                amount, sign = rng.randint(500, 200_000), 1
            else:
                amount, sign = rng.randint(200, 80_000), -1
            new_txs.append({
                "id": f"t-{tx_start + k + 100000:08d}",
                "client_id": c["id"],
                "type": ttype,
                "amount_rub": sign * amount,
                "ts": (TODAY - timedelta(days=rng.randint(0, 90),
                                         hours=rng.randint(0, 23),
                                         minutes=rng.randint(0, 59))).isoformat(),
            })
            k += 1

    # кредитная история для тех, у кого есть кредитные продукты
    new_ch: list[dict] = []
    loans = ("mortgage", "auto_credit", "consumer_credit", "credit_card")
    for c in new_clients:
        if not any(p in c["products"] for p in loans):
            continue
        for _ in range(rng.randint(1, 4)):
            opened = TODAY - timedelta(days=rng.randint(60, 365 * 4))
            principal = rng.randint(50_000, 5_000_000) if "mortgage" in c["products"] \
                else rng.randint(20_000, 800_000)
            if c["has_overdue_history"]:
                overdue = rng.choice([0, 0, 5, 12, 30, 60, 90])
                status = "closed_with_overdue" if overdue > 0 else "active"
            else:
                overdue = 0
                status = rng.choice(["active", "closed_clean"])
            new_ch.append({
                "id": f"ch-{ch_start + len(new_ch) + 1:06d}",
                "client_id": c["id"],
                "product": rng.choice([p for p in c["products"] if p in loans]),
                "principal_rub": principal,
                "term_months": rng.choice([6, 12, 24, 36, 60]),
                "rate_pct": round(rng.uniform(7.5, 24.0), 2),
                "opened_at": opened.date().isoformat(),
                "status": status,
                "overdue_days_max": overdue,
            })

    _append_jsonl(OUT / "clients.jsonl", new_clients)
    _append_jsonl(OUT / "transactions.jsonl", new_txs)
    _append_jsonl(OUT / "credit_history.jsonl", new_ch)
    print(f"added clients: {len(new_clients)} (total {len(clients) + len(new_clients)})")
    print(f"added transactions: {len(new_txs)} (total {len(txs) + len(new_txs)})")
    print(f"added credit_history: {len(new_ch)} (total {len(chist) + len(new_ch)})")


if __name__ == "__main__":
    main()
