# Контракт блока backend

Сюда вписывай ручки, которые твой блок отдаёт наружу. Соседи по команде
видят только этот файл — не код. Если ручка изменилась или появилась новая —
обнови этот файл, иначе сосед о ней не узнает.

## Что я отдаю наружу

### GET /health
Проверка живости. Возвращает `{status, team, block, commit, clients_loaded,
transactions_loaded, credit_cards_loaded}`.

### GET /clients
Список клиентов команды. Параметры запроса (все опциональные):
- `segment` — строка, сегмент клиента;
- `has_overdue` — bool, был ли просрочен платёж;
- `min_income` — int, минимальный доход в рублях;
- `limit` — int, ограничение по числу записей (по умолчанию 50, максимум 500).

Возвращает `{total, items: [клиенты]}`. Клиент — JSON с полями из seed:
`id, name, segment, balance_rub, income_rub, has_overdue_history`, а также
`cashback_balance_rub` (накопленный кешбэк клиента) и другими.

### GET /clients/{client_id}
Полная карточка одного клиента. Возвращает объект клиента. `404`, если не найден.

### GET /transactions/{client_id}
Транзакции клиента, новые сверху. Параметры: `limit` (по умолчанию 20).
Возвращает `{total, items: [транзакции]}`. Транзакция —
`{id, client_id, type, amount_rub, ts, counterparty, cashback_rub}`.
Поле `cashback_rub` — сколько кешбэка начислила эта операция (0, если не начисляла).

### POST /api/transfer
Перевод средств между клиентами команды. Принимает JSON
`{from_client_id, to, amount_rub}`. `to` — это либо id клиента, либо часть
имени получателя (поиск по подстроке). Возвращает `{status, kind
(internal|external), amount_rub, to, from_client_id, new_balance_rub, tx_id, ts}`.
Переводы кешбэк не начисляют.

### GET /cashback/{client_id}
Текущий кешбэк-баланс клиента. Возвращает
`{client_id, cashback_balance_rub, cashback_rate}`. `404`, если клиент не найден.

### POST /api/purchase
Покупка клиента у мерчанта: списывает сумму со счёта и начисляет кешбэк
(сейчас `cashback_rate` = 5%). Принимает JSON
`{client_id, amount_rub, merchant}` (`merchant` опционально). Возвращает
`{status, client_id, amount_rub, merchant, cashback_earned_rub,
new_balance_rub, cashback_balance_rub, tx_id, ts}`. Создаёт транзакцию
типа `purchase` с заполненным `cashback_rub`.

### POST /api/cashback/redeem
Потратить накопленный кешбэк: списывает указанную сумму с кешбэк-баланса и
зачисляет её на обычный счёт клиента. Принимает JSON `{client_id, amount_rub}`.
Возвращает `{status, client_id, redeemed_rub, new_balance_rub,
cashback_balance_rub, tx_id, ts}`. `400`, если кешбэка не хватает.

## Вклады (движение денег)

Открытие вклада списывает деньги с обычного счёта клиента (`balance_rub`) и
держит их во вкладе, пока он не закрыт. Кешбэк на эти операции не начисляется.
Вклад — `{deposit_id, client_id, product, amount_rub, term_months, rate_pct,
status, opened_at, matures_at}`. `matures_at` = дата открытия + `term_months`.

### POST /api/deposits
Открыть вклад: списать `amount_rub` со счёта клиента и записать вклад.
Принимает JSON `{client_id, product, amount_rub, term_months?, rate_pct?}`:
- `client_id` — id клиента, обязателен;
- `product` — код продукта вклада (например `deposit-12m`, `deposit-flex`);
- `amount_rub` — сумма вклада, целое, > 0;
- `term_months` — срок в месяцах (0/отсутствует — без срока, `matures_at` = сегодня);
- `rate_pct` — годовая ставка в процентах (нужна для расчёта процентов при снятии).

Возвращает `{status, client_id, deposit_id, product, amount_rub,
new_balance_rub, matures_at, ts}`. `400`, если `amount_rub` больше баланса
(нехватка средств) или сумма не положительная; `404`, если клиента нет.
Создаёт транзакцию типа `deposit_open` (`amount_rub` отрицательный, без кешбэка).

### POST /api/deposits/{deposit_id}/withdraw
Закрыть вклад и вернуть тело (+ проценты) на счёт клиента (`balance_rub`).
Принимает JSON `{}` или `{early: true}`. Логика процентов: если срок вышел и
снятие не помечено как досрочное — полные проценты за срок; для гибких
продуктов (`deposit-flex`, `savings-flex`) снятие всегда без потери процентов;
для срочного вклада досрочно — сниженные проценты (30% от начисленных).
Полные проценты = `amount_rub * rate_pct/100 * term_months/12`, округление до рубля.
Возвращает `{status, client_id, deposit_id, kind (matured|flex|early),
principal_rub, interest_rub, returned_rub, new_balance_rub, ts}`. `404`, если
вклада нет; `400`, если вклад уже закрыт. Создаёт транзакцию `deposit_withdraw`.

### GET /clients/{client_id}/deposits
Вклады клиента (новые сверху). Возвращает `{client_id, total, items: [вклады]}`.
`404`, если клиента нет.

### GET /deposits/{deposit_id}
Один вклад. Возвращает объект вклада. `404`, если не найден.

## Инвестиции

### GET /instruments
Каталог доступных инструментов с текущей ценой. Возвращает
`{total, items: [{symbol, name, price_rub}]}`. Заявка (`POST .../orders`) должна
слать `symbol` ровно одним из этих кодов. Сейчас в каталоге:
- `OFZ26` — ОФЗ, гособлигация (под продукт «государственные облигации»);
- `FXCB` — фонд корпоративных облигаций (под «фонд корпоблигаций»);
- `FXIM` — индексный ETF на индекс Мосбиржи (под «индексный ETF»);
- `FXEQ` — фонд акций, широкий рынок (под «фонд акций»);
- `SBER`, `GAZP`, `LKOH` — акции голубых фишек (Сбер, Газпром, Лукойл);
- `YNDX` — акция роста (Яндекс);
- `FXGD` — фонд на золото.

### GET /investments/summary
Сводка по всему банку (AUM). Возвращает `{assets_under_management_rub,
invested_rub, unrealized_pnl_rub, investors, orders_total, by_instrument:
[{symbol, name, qty, market_value_rub, holders}]}`. Текущая стоимость считается
по ценам из каталога.

### GET /clients/{client_id}/portfolio
Инвестиционный портфель клиента. Возвращает `{client_id, positions: [...],
market_value_rub, cost_basis_rub, unrealized_pnl_rub}`. Позиция —
`{symbol, name, qty, avg_cost_rub, current_price_rub, market_value_rub,
cost_basis_rub, unrealized_pnl_rub}`. `404`, если клиента нет.

### POST /clients/{client_id}/orders  (он же POST /api/clients/{client_id}/orders)
Заявка на покупку/продажу инструмента. Принимает JSON
`{side, symbol, qty, commission_rub?}`:
- `side` — `buy` или `sell`;
- `symbol` — код инструмента из каталога (`GET /instruments`);
- `qty` — целое число бумаг, > 0;
- `commission_rub` — комиссия банка по сделке (её считает cib, см. его
  `GET /securities`: `commission_pct` + минимум 50 ₽). Опционально; передавай
  уже посчитанную сумму в рублях. Если не передать — 0 (комиссия не берётся).

`buy` списывает `price*qty + commission_rub` со счёта клиента (`balance_rub`) и
добавляет бумаги в портфель; `sell` продаёт бумаги, зачисляет `price*qty` и
удерживает `commission_rub` из выручки. Комиссия проводится как доход банка
(см. `GET /analytics/revenue`). Возвращает
`{status, order, commission_rub, new_balance_rub, portfolio}`, где `order` —
`{order_id, client_id, side, symbol, qty, price_rub, gross_rub, commission_rub,
ts, tx_id, commission_tx_id}`. Сделка создаёт транзакцию
(`invest_buy` / `invest_sell`), а комиссия — отдельную `brokerage_fee`. Ошибки
`400`: неизвестный side, неизвестный инструмент, qty ≤ 0, нехватка средств
(учитывает комиссию), нехватка бумаг. `404`, если клиента нет.

### GET /clients/{client_id}/orders
История заявок клиента, новые сверху. Параметр `limit` (по умолчанию 50).
Возвращает `{total, items: [...]}`. `404`, если клиента нет.

## Продукты клиента

### POST /clients/{client_id}/products  (он же POST /api/clients/{client_id}/products)
Записать новый продукт в профиль клиента — зовёт cib после того, как
подтвердил открытие (вклад, карта и т.п.). Принимает JSON
`{product, opened_at?, source?, details?}`:
- `product` — код продукта, строка (например `deposit`, `credit_card`), обязателен;
- `opened_at` — дата открытия `YYYY-MM-DD`, по умолчанию сегодня;
- `source` — кто оформил, по умолчанию `cib`;
- `details` — произвольный объект с деталями (сумма вклада, срок и т.п.).

Возвращает `{status, client_id, product, already_had, products, event}`, где
`products` — обновлённый список продуктов клиента, `event` — запись журнала
`{event_id, client_id, product, opened_at, source, details, ts}`. Повторное
добавление того же продукта не дублирует его в списке (`already_had=true`),
но всё равно пишется в журнал. `404`, если клиента нет; `400`, если не указан
`product`.

### GET /clients/{client_id}/products
Продукты клиента и журнал их открытий (новые сверху). Возвращает
`{client_id, products, events_total, events: [...]}`. `404`, если клиента нет.

## Рекомендации (next best offer)

Аналитический инструмент: смотрим на данные клиента (доход, остаток,
текущие продукты, риск-скор, просрочки, сегмент, возраст) и предлагаем
продукты, которых у него ещё нет и которые ему подойдут. У каждой
рекомендации — `score` (0..1, уместность), `reason` (причина простыми
словами) и доп. поля (предлагаемая сумма/лимит, ожидаемая выгода).

### GET /clients/{client_id}/recommendations
Предложения для одного клиента, сильнейшие сверху. Параметр `limit`
(по умолчанию 5). Возвращает `{client_id, name, segment, recommendations:
[{product, title, reason, score, ...}]}`. Коды продуктов в рекомендациях:
`deposit-12m`, `deposit-flex`, `credit_card`, `investments`,
`consumer_credit`, `mortgage`, `premium_upgrade`, `cashback_redeem`.
Движок не предлагает то, чем клиент уже владеет: если продукт записан в
`products` (через `POST /clients/{id}/products`) — соответствующая
рекомендация исключается (учитываются разные написания кода: `deposit` ↔
`deposit-12m`, `cashback_card` ↔ `credit_card` и т.п.). `404`, если клиента
нет. cib/retail могут показать это клиенту и сразу провести через нужную
ручку (вклад, заявку, карту).

### GET /recommendations/summary
Сводка по всему банку: для каждого продукта — скольким клиентам его стоит
предложить и суммарный потенциал. Параметр `segment` — посчитать по одному
сегменту. Возвращает `{clients_analysed, by_product: [{product, title,
candidates, potential_amount_rub, potential_annual_benefit_rub}]}`.

## Аналитика привлечения

### GET /analytics/feature-acquisition
Какие фичи приводят и держат клиентов. По существующей базе — у скольких
клиентов есть каждая фича, их ценность (остатки, доход) и в какие годы они
пришли; плюс «живая» атрибуция новых подключений через новые ручки. Возвращает
`{clients_total, by_feature: [{feature, title, clients, share_pct,
total_balance_rub, avg_balance_rub, avg_income_rub, joined_by_year}],
acquisition_by_year, live_adoption: {deposits_opened, credit_cards_issued_via_api,
investment_accounts_opened, product_openings_logged, openings_by_product}, note}`.
`by_feature` — связь, не доказанная причина; `live_adoption` копится с момента
запуска фич и есть настоящая атрибуция.

### GET /analytics/revenue
Доход банка по источникам (например, брокерская комиссия по сделкам). Параметр
`limit` (по умолчанию 20). Возвращает `{total_revenue_rub, by_source:
[{source, amount_rub}], events_total, recent_events: [{source, amount_rub,
client_id, note, ts}]}`. Копится с момента запуска.

### GET /analytics/overview
Сводные показатели клиентской базы (для дашборда). Возвращает
`{clients_total, by_segment, total_balance_rub, avg_balance_rub,
avg_income_rub, total_cashback_rub, deposits_active, deposits_held_rub,
credit_cards, credit_card_debt_rub, investors, assets_under_management_rub,
bank_revenue_rub}`.

### GET /dashboard  (он же GET /)
Готовая HTML-страница с аналитикой по клиентской базе — открывается в браузере,
тянет живые данные из `/analytics/*` и `/recommendations/summary`. Это
страница для человека, а не API; соседям дёргать не нужно.

## Кредитные карты

Карта — это `{card_id, client_id, credit_limit_rub, balance_owed_rub,
available_credit_rub, status, opened_at}`. `available_credit_rub` всегда
считается на лету как `credit_limit_rub - balance_owed_rub`. При загрузке
карта автоматически выпускается каждому клиенту с кредитным продуктом
(лимит ~3 дохода, текущий долг зависит от риск-скора).

### GET /credit-cards
Список карт. Параметры (опциональные): `client_id`, `status`, `limit`
(по умолчанию 50). Возвращает `{total, items: [карты]}` (без истории, но с
`history_count`).

### GET /clients/{client_id}/credit-cards
Все карты одного клиента. Возвращает `{total, items: [карты]}`. `404`, если
клиента нет.

### GET /credit-cards/{card_id}
Полная карточка с историей операций: `{...поля карты, history: [...]}`.
`404`, если карты нет.

### GET /credit-cards/{card_id}/history
История операций по карте, новые сверху. Параметр `limit` (по умолчанию 50).
Возвращает `{total, items: [...]}`. Запись истории —
`{ts, type (charge|payment), amount_rub, balance_owed_rub, ...}`.

### POST /api/credit-cards
Выпуск новой карты. Принимает `{client_id, credit_limit_rub?}`. Если лимит не
указан — считаем от дохода. Возвращает карту с историей. `404`, если клиента нет.

### POST /api/credit-cards/{card_id}/charge
Покупка по карте: увеличивает долг, уменьшает доступный лимит. Принимает
`{amount_rub, merchant?}`. Возвращает `{status, card_id, charged_rub, merchant,
...поля карты}`. `400`, если сумма превышает доступный лимит или карта не active.

### POST /api/credit-cards/{card_id}/payment
Платёж по карте: уменьшает долг, возвращает доступный лимит. Принимает
`{amount_rub}`. Возвращает `{status, card_id, paid_rub, ...поля карты}`. `400`,
если платёж больше текущего долга.

## Кого я зову у соседей

Никого. backend — это ядро данных, оно ничего не зовёт у retail и cib.

## Где работает блок локально

`http://localhost:8003` (порт фиксируется docker-compose).
