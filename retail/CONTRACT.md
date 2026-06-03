# Контракт блока retail

Сюда вписывай ручки, которые твой блок отдаёт наружу. Соседи по команде
видят только этот файл — не код. Если ручка изменилась или появилась новая —
обнови этот файл, иначе сосед о ней не узнает.

## Что я отдаю наружу

### GET /health
Проверка живости. Возвращает `{status, team, block, commit, backend_url, cib_url}`.

### GET /
HTML мобильного банка. Для человека, не для других блоков.
Includes language toggle (RU/EN) and two tabs: Transfers and Loans.

### GET /clients
Список клиентов команды (прокси к backend). Параметры запроса передаются как есть.
Возвращает `{total, items: [клиенты]}`.

### GET /transactions/{client_id}
Транзакции клиента (прокси к backend). Возвращает `{total, items: [транзакции]}`.

### POST /api/transfer
Перевод средств между клиентами команды. Принимает JSON
`{from_client_id, to, amount_rub}`. Возвращает `{status, kind, amount_rub, to,
from_client_id, new_balance_rub, tx_id, ts}`.

### GET /products
Каталог продуктов (прокси к cib). Возвращает `{total, items: [продукты]}`.

### GET /api/card-info/{client_id}
Debit card summary with cashback. Fetches customer profile and transactions
from backend, cashback rates from CIB (GET /cashback-rates, if available).
Returns `{client_id, customer_name, card_number_masked, balance_rub,
total_cashback_rub, cashback_transactions: [{tx_id, type, amount_rub,
cashback_rub, rate, ts, counterparty}], rates, rates_source}`.

### GET /api/credit-card/{client_id}
Credit card summary. Tries backend `GET /credit-card/{client_id}` for real
data; if unavailable, simulates from customer profile. Checks eligibility
via CIB `POST /credit/decide` with product_id `"credit-card"`.
Returns `{client_id, customer_name, eligible, explanation, card_number_masked,
credit_limit_rub, balance_owed_rub, available_rub, min_payment_rub,
interest_rate_pct, grace_period_days, source}`.

### GET /api/deposits/{client_id}
Savings account overview. Fetches deposit products from CIB (kind=deposit)
and existing deposits from backend (GET /deposits/{client_id} if available).
Returns `{client_id, customer_name, balance_rub, deposit_products,
existing_deposits, total_deposited_rub, total_interest_rub, deposits_source}`.

### POST /api/deposit-open
Open a new deposit. Accepts `{client_id, product_id, amount_rub, term_months}`.
Tries backend POST /deposits; if unavailable, returns simulated confirmation
with `{status, client_id, product_id, amount_rub, term_months, rate_pct,
estimated_interest_rub, message, source}`.

### GET /api/investments/{client_id}
Investment portfolio overview. Fetches investment instruments from CIB
/products, asks CIB POST /investment/recommend for the customer's investor
profile and suitable risk level (tags each instrument with `suitable` +
`risk` band), and reads holdings from backend (GET /portfolio/{client_id} if
available). Returns `{client_id, customer_name, balance_rub, investor_profile,
max_risk_level, instruments, holdings, total_invested_rub, total_value_rub,
gain_rub, gain_pct, portfolio_source}`.

### POST /api/invest
Place an investment order. Accepts `{client_id, instrument_id, amount_rub}`.
First runs a CIB suitability check (POST /investment/suitability). If the
product does not match the customer's risk profile, returns
`{status: "unsuitable", reasons, suitable_alternatives, investor_profile,
max_risk_level, product_risk_level, ...}`. If suitable, places the order via
backend POST /portfolio/buy; if unavailable, returns a simulated confirmation
`{status: "ok", instrument_name, amount_rub, expected_return_pct,
projected_value_1y_rub, source}`.

### POST /api/credit-card-payment
Payment toward credit card balance. Accepts `{client_id, amount_rub}`.
Tries backend `POST /credit-card-payment`; if unavailable, returns
simulated confirmation `{status, client_id, amount_rub, message, source}`.

### POST /api/credit-apply
Заявка на кредит. Принимает JSON `{client_id, product_id, amount_rub}`.
Orchestration: fetches customer profile from backend, then asks cib
`POST /api/credit-decision` for the verdict. If cib endpoint is not yet
available, uses a simple heuristic (income >= 30k, no overdue, amount <= 12x income).
Возвращает `{status: "approved"|"declined", client_id, product_id,
amount_rub, max_amount_rub, reason, source}`.

## Кого я зову у соседей

- backend: `GET /clients`, `GET /clients/{id}`, `GET /transactions/{id}`, `POST /api/transfer`, `GET /credit-card/{client_id}` (when available), `POST /credit-card-payment` (when available), `GET /deposits/{client_id}` (when available), `POST /deposits` (when available), `GET /portfolio/{client_id}` (when available), `POST /portfolio/buy` (when available)
- cib: `GET /products`, `POST /credit/decide` (payload: `{client_id, product_id}`), `POST /card/activate` (payload: `{client_id, product_id: "card-debit-cashback"}`, returns personalised cashback rates by segment), `POST /card/credit-limit` (payload: `{client_id, product_id: "card-credit"}`, returns personalised credit limit or secured card fallback), `POST /deposit/open` (payload: `{client_id, product_id, amount_rub}`, returns rate, maturity, projected interest), `POST /investment/recommend` (payload: `{client_id}`, returns investor profile + suitable products), `POST /investment/suitability` (payload: `{client_id, product_id, amount_rub}`, returns suitability verdict + alternatives)

## Где работает блок локально

`http://localhost:8001` (порт фиксируется docker-compose).
