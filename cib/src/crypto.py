"""Preview-only crypto top-up calculations for the workshop demo."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()
DEMO_RATE = Decimal("100.00")

PRODUCT = {
    "id": "crypto-topup-demo", "kind": "topup", "name": "Пополнение USDT — учебная демонстрация",
    "asset": "USDT", "mode": "demo", "demo_only": True,
    "min_amount_rub": 1000, "max_amount_rub": 100000,
    "demo_rate_rub_per_unit": "100.00", "rate_source": "fixed_demo_not_market",
    "fee_rub": "0.00", "quote_ttl_seconds": 300,
    "preview_available": True, "application_available": False,
    "availability_reason": "Расчёт доступен; учебное зачисление ожидает подключения backend и retail",
}


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: Literal["USDT"] = "USDT"
    amount_rub: Decimal = Field(ge=1000, le=100000, max_digits=8, decimal_places=2)


@router.post("/crypto/quote")
async def quote(body: QuoteRequest):
    now = datetime.now(timezone.utc)
    amount = body.amount_rub.quantize(Decimal("0.01"))
    crypto = (amount / DEMO_RATE).quantize(Decimal("0.000001"), rounding=ROUND_UP)
    return {
        "product_id": PRODUCT["id"], "mode": "demo", "demo_only": True,
        "asset": body.asset, "amount_rub": str(amount), "credit_amount_rub": str(amount),
        "crypto_amount": str(crypto), "rate_rub_per_unit": str(DEMO_RATE),
        "rate_source": "fixed_demo_not_market", "fee_rub": "0.00",
        "created_at": now.isoformat(), "expires_at": (now + timedelta(seconds=300)).isoformat(),
        "status": "preview", "can_accept_payment": False,
        "notice": "Учебный расчёт. Курс условный, реальные переводы не принимаются. Баланс не изменён.",
    }


@router.get("/crypto/demo", response_class=HTMLResponse)
async def demo():
    return """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Учебное пополнение USDT</title><style>
body{font:18px system-ui;background:#0c0d10;color:#e8e9ec;max-width:650px;margin:50px auto;padding:24px}
input,button{font:inherit;padding:12px;border-radius:8px;margin:12px 0}button{background:#ffed00;color:#111;border:0;cursor:pointer}
small{display:block;color:#bbb}#result{line-height:1.7;white-space:pre-line}a{color:#ffed00}
</style><a href="/">← Каталог</a><h1>Пополнение USDT</h1>
<p>Учебная демонстрация: реальные переводы не принимаются.</p>
<small>Условный курс: 1 USDT = 100 ₽. Это не рыночная котировка. Комиссия в демонстрации — 0 ₽.</small>
<form id="form"><label for="amount">Сколько рублей хотите зачислить?</label><br>
<input id="amount" type="number" min="1000" max="100000" step="0.01" value="10000" required>
<button>Рассчитать</button></form><div id="result" role="status" aria-live="polite"></div>
<small>Это предварительный расчёт. Зачисление пока не подключено.</small>
<script>document.getElementById('form').onsubmit=async function(e){e.preventDefault();
const out=document.getElementById('result');out.textContent='Рассчитываем…';
try{const r=await fetch('/crypto/quote',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({asset:'USDT',amount_rub:document.getElementById('amount').value})});
if(!r.ok){out.textContent='Введите сумму от 1 000 до 100 000 ₽, не более двух знаков после запятой.';return;}
const d=await r.json();out.textContent='Условная сумма: '+d.crypto_amount+' USDT\\nК зачислению в демонстрации: '+d.credit_amount_rub+' ₽\\nРасчёт действителен 5 минут.\\n'+d.notice;
}catch(err){out.textContent='Расчёт временно недоступен. Попробуйте ещё раз.'}};</script></html>"""
