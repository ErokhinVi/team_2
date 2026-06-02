# Контракт блока retail

Сюда вписывай ручки, которые твой блок отдаёт наружу. Соседи по команде
видят только этот файл — не код. Если ручка изменилась или появилась новая —
обнови этот файл, иначе сосед о ней не узнает.

## Что я отдаю наружу

### GET /health
Проверка живости. Возвращает `{status, team, block, commit, backend_url, cib_url}`.

### GET /
HTML мобильного банка. Для человека, не для других блоков.

### GET /clients
Список клиентов команды (прокси к backend). Параметры запроса передаются как есть.
Возвращает `{total, items: [клиенты]}`.

### GET /transactions/{client_id}
Транзакции клиента (прокси к backend). Возвращает `{total, items: [транзакции]}`.

### GET /products
Каталог продуктов команды (прокси к cib). Вкладка «Кредиты» берёт отсюда
кредитные продукты и их ставки. Возвращает `{total, items: [продукты]}`.

### POST /api/transfer
Перевод средств между клиентами команды. Принимает JSON
`{from_client_id, to, amount_rub}`. Возвращает `{status, kind, amount_rub, to,
from_client_id, new_balance_rub, tx_id, ts}`.

### POST /api/credit-apply
Заявка на кредит. Принимает JSON `{client_id, product_id?, amount_rub, term_months?}`.
Оркестрация: берёт карточку клиента в backend, затем просит решение у cib
(`POST /credit/decide`). Возвращает `{client, result}` с решением cib, либо
`{decision: "pending_integration", client, message}`, пока cib не опубликовал
ручку решения.

## Кого я зову у соседей

- backend: `GET /clients`, `GET /clients/{id}`, `GET /transactions/{id}`, `POST /api/transfer`
- cib: `GET /products` (каталог), `POST /credit/decide` (решение по заявке —
  жду, когда сосед опубликует эту ручку в своём контракте)

## Где работает блок локально

`http://localhost:8001` (порт фиксируется docker-compose).
