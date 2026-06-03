# Контракт блока cib

Сюда вписывай ручки, которые твой блок отдаёт наружу. Соседи по команде
видят только этот файл — не код. Если ручка изменилась или появилась новая —
обнови этот файл, иначе сосед о ней не узнает.

## Что я отдаю наружу

### GET /health
Проверка живости. Возвращает `{status, team, block, commit, backend_url, products}`.

### GET /products
Product catalogue. Returns `{total, items: [products]}`. Each product has at least `{id, kind, name}`. Cards may have `cashback_categories`; credit/deposit products have `rate_pct`.

Current products:
- `card-debit-cashback` — Debit card with cashback (groceries/transport/other, rates vary by segment)
- `card-credit` — Credit card, 24.9%, 55-day grace period
- `card-credit-secured` — Secured credit card for borderline customers, 29.9%, 30-day grace, limit up to 30,000 rubles
- `deposit-base` — Term deposit, 14%
- `credit-consumer` — Consumer loan, 18.9%

### GET /
HTML с каталогом продуктов. Для человека, не для других блоков.

### POST /credit/decide

Credit decision for a customer applying for a product. Request body (JSON):
`{ "client_id": "<string>", "product_id": "<string>" }`

`product_id` must be a credit product — currently only `"credit-consumer"` (consumer loan, 18.9 %).

Returns:
```json
{
  "client_id": "c-01000",
  "product_id": "credit-consumer",
  "approved": true,
  "reasons": [],
  "explanation": "Congratulations, your application has been approved.",
  "customer_name": "Анна Козлова"
}
```
`approved` is `true` or `false`. `reasons` lists why a decision was declined (empty on approval).
HTTP 404 if client or product is not found. HTTP 400 if product is not a credit product.

### POST /card/credit-limit

Credit card limit decision for a customer. Request body: `{ "client_id": "<string>", "product_id": "card-credit" }`

Returns a personalised credit limit based on income × segment multiplier, adjusted down by risk score. Limit is rounded to the nearest 10,000 rubles.

```json
{
  "client_id": "c-01000",
  "product_id": "card-credit",
  "approved": true,
  "limit_rub": 90000,
  "rate_pct": 24.9,
  "grace_period_days": 55,
  "segment": "mass",
  "reasons": [],
  "customer_name": "Анна Козлова"
}
```

If the customer doesn't qualify for the standard card but is borderline (risk ≤ 0.72, income ≥ 18,000, no overdue history), the response automatically offers the secured card instead — `product_id` in the response will be `"card-credit-secured"` and a `note` field explains why. Only a hard decline (overdue history, risk > 0.72, or income < 18,000) returns `approved: false`.

### POST /card/activate

Activate a debit card for a customer. Request body: `{ "client_id": "<string>", "product_id": "<string>" }`

Currently supports `"card-debit-cashback"`. Returns personalised cashback rates based on the customer's segment:

```json
{
  "client_id": "c-01000",
  "product_id": "card-debit-cashback",
  "activated": true,
  "customer_name": "Анна Козлова",
  "segment": "mass",
  "cashback_rates_pct": { "groceries": 2.0, "transport": 1.5, "other": 0.5 },
  "message": "Card activated. Your cashback: groceries 2.0%, transport 1.5%, other 0.5%."
}
```

Rates by segment — mass: 2/1.5/0.5%, mass_affluent: 3/2/1%, premium: 5/3/1.5%, private: 7/5/2%.

## Кого я зову у соседей

- backend: `GET /clients/{client_id}` — full customer card (income, risk score, overdue history)
- retail: я никого не зову у retail — это retail зовёт меня

## Где работает блок локально

`http://localhost:8002` (порт фиксируется docker-compose).
