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

### POST /api/credit-apply
Заявка на кредит. Принимает JSON `{client_id, product_id, amount_rub}`.
Orchestration: fetches customer profile from backend, then asks cib
`POST /api/credit-decision` for the verdict. If cib endpoint is not yet
available, uses a simple heuristic (income >= 30k, no overdue, amount <= 12x income).
Возвращает `{status: "approved"|"declined", client_id, product_id,
amount_rub, max_amount_rub, reason, source}`.

## Кого я зову у соседей

- backend: `GET /clients`, `GET /clients/{id}`, `GET /transactions/{id}`, `POST /api/transfer`
- cib: `GET /products`, `POST /api/credit-decision` (when available; payload: `{client_id, product_id, amount_rub, customer: {...}}`)

## Где работает блок локально

`http://localhost:8001` (порт фиксируется docker-compose).
