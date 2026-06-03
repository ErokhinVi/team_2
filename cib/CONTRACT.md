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
- `deposit-3m`  — 3-month term deposit, 13%, min 10,000 rubles
- `deposit-6m`  — 6-month term deposit, 15%, min 10,000 rubles
- `deposit-12m` — 12-month term deposit, 17%, min 30,000 rubles
- `deposit-flex` — Flexible savings account, 9.5%, withdraw anytime, min 1,000 rubles
- `credit-consumer` — Consumer loan, base 18.9% (risk-based: personalised rate returned by /credit/decide)
- `credit-auto` — Car loan, base 13.9% (secured, cheaper than consumer)
- `credit-refinance` — Refinancing existing debt, base 15.9% (see POST /credit/refinance)
- `mortgage` — Mortgage, from 16%, up to 30 years, min 20% down payment
- Investments (each has `subtype`, `risk_level` 1–5, `expected_return_pct`, `min_investment_rub`):
  - `inv-ofz` — Government bonds (OFZ), risk 1, ~13%
  - `inv-corp-bond` — Corporate bond fund, risk 2, ~16%
  - `inv-etf-index` — Moscow Exchange index ETF, risk 3, ~18%
  - `inv-equity-fund` — Equity fund, risk 3, ~19%
  - `inv-bluechip` — Blue-chip stocks, risk 4, ~22%
  - `inv-growth` — Growth stocks, risk 5, ~28%
  - `inv-gold` — Gold fund (FXGD), risk 2, ~11%

### GET /
HTML с каталогом продуктов. Для человека, не для других блоков.

### POST /credit/decide

Credit decision for a customer applying for a product. Request body (JSON):
`{ "client_id": "<string>", "product_id": "<string>" }`

`product_id` must be a credit-type product: `"credit-consumer"` (consumer loan, 18.9 %) or the credit card `"card-credit"` (alias `"credit-card"` also accepted).

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
`approved` is `true` or `false`. `reasons` lists why a decision was declined (empty on approval). On approval, `rate_pct` is the **personalised, risk-based** rate (safer customers pay less, riskier more) and `base_rate_pct` is the list rate.
HTTP 404 if client or product is not found. HTTP 400 if product is not a credit product.

### POST /credit/refinance

Refinancing offer — takes over the customer's existing debt at a lower, risk-based rate and shows the saving. Request body: `{ "client_id": "<string>", "current_balance_rub": <number>, "current_rate_pct": <number>, "term_months": <int, default 36> }`.

Returns `{approved, beneficial, current_rate_pct, new_rate_pct, balance_rub, term_months, old_monthly_payment_rub, new_monthly_payment_rub, monthly_saving_rub, total_saving_rub, reasons, customer_name}`. `beneficial` is true when the new rate genuinely lowers the payment. Declined (`approved: false`) for overdue history, risk > 0.65, or income below 30,000.

### GET /clients/{client_id}/pre-approved

Pre-approved offers — runs cib's decision logic proactively so the app can show "you're already approved for X" instead of making the customer apply. Skips products the customer already holds. Returns `{client_id, customer_name, total, offers: [...]}`. Each offer:

```json
{
  "product_id": "credit-consumer", "type": "loan", "name": "Потребительский кредит",
  "headline": "You're pre-approved for a loan up to 480 000 ₽",
  "amount_rub": 480000, "rate_pct": 18.9,
  "action": { "method": "POST", "path": "/credit/decide" }
}
```

Covers consumer loans (`amount_rub`), credit cards (`limit_rub`, standard or secured) and mortgages (`max_loan_rub`, 20-yr pre-qualification). The app displays the headline and, on a tap, calls `action` to formalise it. Empty `offers` if the customer pre-qualifies for nothing new.

### GET /clients/{client_id}/next-best-offers

Turns backend's analytical recommendations (`GET /clients/{id}/recommendations`) into ready-to-act offers. For each suggestion, attaches cib's real product terms and the exact call the app should make. Param `limit` (default 5).

Returns `{client_id, name, segment, total, offers: [...]}`. Each offer is backend's recommendation (`product, title, reason, score, ...`) plus a `cib` block:

```json
{
  "product": "deposit-12m", "title": "...", "reason": "idle cash earning nothing", "score": 0.82,
  "cib": {
    "available": true, "product_id": "deposit-12m", "name": "Депозит 12 месяцев", "kind": "deposit",
    "terms": { "rate_pct": 17.0, "term_months": 12 },
    "action": { "method": "POST", "path": "/deposit/open" }
  }
}
```

`cib.available` is false only for codes that belong to backend (`premium_upgrade`, `cashback_redeem` → `handled_by: "backend"`), with a `note` explaining. The app shows the offer and routes the customer to `cib.action`.

Where the customer is pre-approved, the `cib` block also carries a `pre_approved` object (`headline` plus `amount_rub`/`limit_rub`/`max_loan_rub` and `rate_pct`) — so loan, credit-card and mortgage suggestions can show "you're already approved for X" right in the feed.

### POST /mortgage/decide

Mortgage decision for a customer. Request body: `{ "client_id": "<string>", "property_price_rub": <number>, "down_payment_rub": <number>, "term_years": <int, default 20> }`.

Checks the down payment (min 20%), no overdue history, risk score ≤ 0.55, income ≥ 40,000, and that the monthly annuity payment is ≤ 50% of monthly income. Returns:

```json
{
  "client_id": "c-01004", "product_id": "mortgage", "approved": true,
  "property_price_rub": 8000000, "down_payment_rub": 2000000,
  "loan_amount_rub": 6000000, "down_payment_pct": 25.0, "ltv_pct": 75.0,
  "rate_pct": 16.0, "term_years": 20, "monthly_payment_rub": 83451,
  "reasons": [], "explanation": "...", "customer_name": "Олег Кузнецов"
}
```

`approved: false` with `reasons` if any rule fails. HTTP 400 on invalid price/down payment. On approval the mortgage is recorded on the customer's profile via backend `POST /clients/{id}/products` (response includes `recorded`, best-effort).

### POST /investment/suitability

Checks whether an investment product matches a customer's risk profile (regulatory suitability). Request body: `{ "client_id": "<string>", "product_id": "<string>", "amount_rub": <number, optional> }`

The investor profile is derived from age, income and balance (NOT credit risk score). Profiles: conservative (max risk 1) → aggressive (max risk 5). A balance under 50,000 rubles is capped to conservative. If `amount_rub` is given, also enforces a concentration limit (max 50% of balance into a single risk-4+ product).

```json
{
  "client_id": "c-01004",
  "product_id": "inv-growth",
  "product_name": "Акции роста",
  "suitable": false,
  "reasons": ["product risk level 5 exceeds the customer's suitable level 3 (balanced profile)"],
  "investor_profile": "balanced",
  "max_risk_level": 3,
  "product_risk_level": 5,
  "suitable_alternatives": [{ "id": "inv-equity-fund", "name": "Фонд акций", "risk_level": 3, "expected_return_pct": 19.0 }],
  "customer_name": "Олег Кузнецов"
}
```

### POST /investment/recommend

Returns the list of investment products suitable for a customer, sorted by expected return. Request body: `{ "client_id": "<string>" }`. Returns `{client_id, customer_name, investor_profile, max_risk_level, total, items: [...]}`.

### GET /securities

Tradable securities with their trading terms. CIB owns the trading **terms** (`lot_size`, `commission_pct`, `min_order_rub`, suitability); the `ticker` matches backend's live `GET /instruments` catalogue, since backend executes orders by that exact code. Returns `{total, items: [{id, ticker, asset_type, name, risk_level, expected_return_pct, lot_size, commission_pct, min_order_rub, alt_tickers?}]}`.

Tickers (aligned to backend's catalogue): `inv-ofz`→`OFZ26`, `inv-corp-bond`→`FXCB`, `inv-etf-index`→`FXIM`, `inv-equity-fund`→`FXEQ`, `inv-bluechip`→`SBER` (also `GAZP`, `LKOH`), `inv-growth`→`YNDX`.

### POST /investment/order-check

Validates a proposed trade and returns the commission. Request body: `{ "client_id": "<string>", "product_id": "<string>", "side": "buy"|"sell", "qty": <int>, "price_rub": <number, optional> }`. If `price_rub` is omitted, CIB prices it from backend's live catalogue by ticker.

Enforces CIB's trading rules: valid side, positive whole lots (multiple of `lot_size`), minimum order value (buys), suitability vs the customer's investor profile (buys), and sufficient cash to cover trade value **plus** commission (buys). Commission = `max(gross × commission_pct%, 50 ₽)`.

```json
{
  "client_id": "c-01004", "product_id": "inv-etf-index", "ticker": "FXIM",
  "asset_type": "etf", "side": "buy", "qty": 100, "price_rub": 95.0,
  "gross_rub": 9500.0, "commission_pct": 0.2, "commission_rub": 50.0,
  "total_cost_rub": 9550.0, "net_proceeds_rub": null,
  "valid": true, "reasons": [], "customer_name": "Олег Кузнецов"
}
```

For a `sell`, `net_proceeds_rub` (gross − commission) is returned instead of `total_cost_rub`; share ownership is validated by backend at execution. `valid: false` with `reasons` if any rule fails.

### POST /investment/order-plan

Bridges a CIB investment product to an executable backend order. Request body: `{ "client_id": "<string>", "product_id": "<string>", "amount_rub": <number> }`.

Runs the suitability check; if suitable, maps the product to a backend instrument symbol, prices it against backend `GET /instruments`, and computes the quantity that fits within `amount_rub`. Returns:

```json
{
  "client_id": "c-01000",
  "product_id": "inv-etf-index",
  "suitable": true,
  "order": { "side": "buy", "symbol": "FXIM", "qty": 100, "price_rub": 95.0, "est_cost_rub": 9500.0 },
  "executable": true,
  "execute_via": "POST <backend>/clients/{client_id}/orders",
  "note": null
}
```

Retail posts the returned `order` to backend `POST /clients/{client_id}/orders`. If the product is unsuitable, `suitable: false` and `order: null`. If the symbol mapping isn't yet confirmed against backend's catalogue, `executable: false` with an explanatory `note` (no wrong order is produced).

**Note:** the symbol map (CIB product → backend instrument) is provisional. If a guess doesn't match, the response sets `executable: false`, a `note`, and lists the real `available_symbols` from backend's live catalogue — so the correct code is visible and the map is fixed in one line.

### POST /deposit/open

Open a deposit for a customer. Request body: `{ "client_id": "<string>", "product_id": "<string>", "amount_rub": <number> }`

Returns confirmation with rate, maturity date, and projected interest earned:

```json
{
  "client_id": "c-01000",
  "product_id": "deposit-12m",
  "product_name": "Депозит 12 месяцев",
  "opened": true,
  "amount_rub": 100000,
  "rate_pct": 17.0,
  "term_months": 12,
  "early_withdrawal": false,
  "opened_at": "2026-06-03",
  "matures_at": "2027-06-03",
  "projected_interest_rub": 17000,
  "customer_name": "Анна Козлова"
}
```

For `deposit-flex`, `term_months` and `matures_at` are null; `early_withdrawal` is true.
HTTP 400 if amount is below the product minimum **or** the customer has insufficient funds. HTTP 404 if client unknown.

This endpoint now actually moves the money: it calls backend `POST /api/deposits` to debit the customer's balance and book the deposit. The response includes `deposit_id` and `new_balance_rub` from backend (keep the `deposit_id` — it's needed to withdraw later).

### POST /deposit/withdraw

Close a deposit and return the money (+ interest) to the customer. Request body: `{ "deposit_id": "<string>", "early": <bool, optional> }`. Proxies backend `POST /api/deposits/{deposit_id}/withdraw`. Returns `{status, client_id, deposit_id, kind, principal_rub, interest_rub, returned_rub, new_balance_rub, ts}`. Flexible deposits always return full interest; fixed-term pulled early get reduced interest; at maturity, full interest. HTTP 404 if the deposit is unknown.

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

On activation the card is also recorded on the customer's profile via backend `POST /clients/{id}/products`. The response includes `recorded` (true/false) — best-effort, so a transient backend hiccup won't block the activation itself.

## Кого я зову у соседей

- backend: `GET /clients/{client_id}` — full customer card (income, risk score, overdue history)
- retail: я никого не зову у retail — это retail зовёт меня

## Где работает блок локально

`http://localhost:8002` (порт фиксируется docker-compose).
