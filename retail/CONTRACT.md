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

### GET /api/car-loan/{client_id}
Car-loan screen overview. Returns customer profile, the bank's car-loan policy
(default rate, min down payment %, max DTI, term range, min loan), and existing
car loans read from backend's customer product log
(`GET /clients/{id}/products`, events with product matching `car-loan`/`auto-loan`).
Returns `{client_id, customer_name, income_rub, balance_rub, default_rate_pct,
min_down_payment_pct, max_dti_pct, min_term_years, max_term_years, min_loan_rub,
existing_loans, loans_source}`.

### POST /api/car-loan/quote
Live car-loan quote. Accepts `{client_id, car_price_rub, down_payment_rub,
term_years}`. Tries CIB POST /car-loan/decide (when shipped); otherwise
computes locally with the annuity formula. Returns the same shape as the
mortgage quote endpoint plus `car_price_rub`.

### POST /api/car-loan/apply
Submit a car-loan application. Same payload as /quote. Tries CIB
POST /car-loan/decide; if cib doesn't yet record the loan on the customer
profile, retail writes the event via backend POST /clients/{id}/products
(`product: "car-loan"`) so the loan shows up on the customer screen.

### GET /api/mortgage/{client_id}
Mortgage screen overview. Returns customer income/balance, the bank's mortgage
policy (default rate, min down payment %, max DTI, term range, min loan), and
existing mortgages from backend if available. Returns `{client_id,
customer_name, income_rub, balance_rub, default_rate_pct, min_down_payment_pct,
max_dti_pct, min_term_years, max_term_years, min_loan_rub, existing_mortgages,
mortgages_source}`.

### POST /api/mortgage/quote
Live mortgage quote — no commitment. Accepts `{client_id, property_price_rub,
down_payment_rub, term_years}`. Tries CIB POST /mortgage/quote (when shipped);
otherwise computes locally using the annuity formula. Returns
`{approved, rate_pct, loan_amount_rub, monthly_payment_rub, total_to_pay_rub,
total_interest_rub, ltv_pct, dti_pct, term_years, term_months, reasons, source}`.

### POST /api/mortgage/apply
Submit a mortgage application. Accepts the same payload as /quote. Tries CIB
POST /mortgage/apply for the decision; on approval, tries backend POST
/clients/{id}/mortgages to open the account. Returns `{status:
"approved"|"declined", client_id, mortgage_id?, loan_amount_rub, rate_pct,
term_years, monthly_payment_rub, ltv_pct, dti_pct, total_to_pay_rub?, reasons?,
source}`.

### GET /api/offers/{client_id}
Personalised next-best-offers for the home screen. Proxies CIB
`GET /clients/{id}/next-best-offers`; falls back to backend
`GET /clients/{id}/recommendations` if CIB is unreachable. Returns
`{client_id, name, segment, total, offers: [...], source}`. Each offer
carries CIB's packaging (`cib.kind`, `cib.product_id`, `cib.terms`,
`cib.action`) plus backend's `product, title, reason, score`. When a
customer is pre-approved, the `cib` block also includes a `pre_approved`
object with `headline`, `amount_rub`/`limit_rub`/`max_loan_rub`, and
`rate_pct` — the UI shows these as prominent green banners on the home
screen.

### POST /api/deposit-withdraw
Close a deposit and return funds + interest. Accepts `{deposit_id, early?}`.
Routes via CIB `POST /deposit/withdraw` (which proxies to backend so the money
actually moves); falls back to backend `POST /api/deposits/{id}/withdraw`.
Returns `{status, client_id, deposit_id, kind (matured|flex|early),
principal_rub, interest_rub, returned_rub, new_balance_rub, ts, source}`.

### POST /api/cashback-redeem
Move accumulated cashback to the customer's main balance. Accepts
`{client_id, amount_rub}`. Proxies backend `POST /api/cashback/redeem`.
Returns `{status, client_id, redeemed_rub, new_balance_rub,
cashback_balance_rub, tx_id, ts, source}`.

### GET /api/referrals/{client_id}
Member-Get-Member invite screen state. Returns the customer's referral code
(currently their client_id, uppercased), the friends they've invited so far,
who invited them (if anyone), and totals: `{client_id, customer_name, code,
share_text, invited: [{invitee_id, invitee_name, at, bonus_rub, bonus_paid}],
invited_count, invited_by, inviter_name, bonus_per_referral_rub,
bonus_earned_rub}`.

### POST /api/referrals/redeem
Redeem a friend's code. Accepts `{client_id, code}`. Returns
`{status: "ok"|"error", inviter_id, inviter_name, bonus_rub, bonus_paid,
reason?}` — `reason` values: `code_required`, `self_referral`, `code_invalid`,
`already_used`, `not_allowed`. Best-effort credits both sides via backend
`POST /clients/{id}/credit-cashback` if that endpoint exists.

### POST /api/credit-apply
Заявка на кредит. Принимает JSON `{client_id, product_id, amount_rub}`.
Orchestration: fetches customer profile from backend, then asks cib
`POST /api/credit-decision` for the verdict. If cib endpoint is not yet
available, uses a simple heuristic (income >= 30k, no overdue, amount <= 12x income).
Возвращает `{status: "approved"|"declined", client_id, product_id,
amount_rub, max_amount_rub, rate_pct, base_rate_pct, reason, source}`.
On approval, `rate_pct` is the customer's personalised risk-based rate and
`base_rate_pct` is the list rate (when CIB provides them).

### POST /api/credit/refinance
Refinancing application. Accepts `{client_id, current_balance_rub,
current_rate_pct, term_months (default 36)}`. Proxies CIB
`POST /credit/refinance`. Returns `{approved, beneficial, current_rate_pct,
new_rate_pct, balance_rub, term_months, old_monthly_payment_rub,
new_monthly_payment_rub, monthly_saving_rub, total_saving_rub, reasons,
customer_name, source}`. The UI shows the monthly saving and total saving
to the customer, and flags when refinancing isn't beneficial.

## Кого я зову у соседей

- backend: `GET /clients`, `GET /clients/{id}`, `GET /transactions/{id}`, `POST /api/transfer`, `GET /credit-card/{client_id}` (when available), `POST /credit-card-payment` (when available), `GET /clients/{id}/deposits`, `POST /deposits` (fallback), `GET /cashback/{client_id}`, `POST /api/cashback/redeem`, `POST /clients/{id}/credit-cashback` (when shipped — payload `{amount_rub, source}`, used to pay out MGM referral bonus to both parties), `GET /instruments`, `GET /clients/{id}/portfolio`, `GET /clients/{id}/orders`, `POST /clients/{id}/orders` (execute buy/sell), `GET /clients/{id}/recommendations` (fallback for offers)
- cib: `GET /products`, `POST /credit/decide`, `POST /credit/refinance`, `POST /card/activate`, `POST /card/credit-limit`, `POST /deposit/open`, `POST /deposit/withdraw`, `POST /investment/recommend`, `POST /investment/suitability`, `POST /investment/order-plan`, `POST /investment/order-check`, `POST /mortgage/decide`, `GET /clients/{id}/next-best-offers` (includes `pre_approved` blocks on loan/card/mortgage offers), `GET /clients/{id}/pre-approved`, `POST /car-loan/decide` (when shipped — payload `{client_id, car_price_rub, down_payment_rub, term_years}`, returns the same decision shape as `/mortgage/decide`; CIB records the loan on the customer profile on approval), `POST /referral/validate` (when shipped)

## Где работает блок локально

`http://localhost:8001` (порт фиксируется docker-compose).
