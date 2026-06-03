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

## Инвестиции

### GET /instruments
Каталог доступных инструментов с текущей ценой. Возвращает
`{total, items: [{symbol, name, price_rub}]}`.

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
Заявка на покупку/продажу инструмента. Принимает JSON `{side, symbol, qty}`:
- `side` — `buy` или `sell`;
- `symbol` — код инструмента из каталога (`GET /instruments`);
- `qty` — целое число бумаг, > 0.

`buy` списывает `price*qty` с обычного счёта клиента (`balance_rub`) и
добавляет бумаги в портфель; `sell` продаёт бумаги и зачисляет деньги на счёт.
Возвращает `{status, order, new_balance_rub, portfolio}`, где `order` —
`{order_id, client_id, side, symbol, qty, price_rub, gross_rub, ts, tx_id}`.
Каждая заявка создаёт транзакцию (`invest_buy` / `invest_sell`). Ошибки `400`:
неизвестный side, неизвестный инструмент, qty ≤ 0, нехватка средств на покупку,
нехватка бумаг на продажу. `404`, если клиента нет.

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
