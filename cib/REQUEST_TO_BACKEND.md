# Request from CIB to backend — deposit money movement

Hi! CIB already confirms deposit openings (`POST /deposit/open`) and you already
let us record the product on a profile (`POST /clients/{id}/products`). The one
missing piece is **moving the money** when a deposit is opened: the amount should
leave the customer's spendable balance and be held in the deposit, then be
returned (with interest) at maturity / on withdrawal.

`POST /api/purchase` isn't right here — it accrues 5% cashback. `POST /api/transfer`
is customer-to-customer. We need a dedicated deposit movement.

## Please add

### POST /api/deposits

Open a deposit: debit the customer's balance by `amount_rub` and book the deposit.

Request body:
```json
{
  "client_id": "c-01000",
  "product": "deposit-12m",
  "amount_rub": 100000,
  "term_months": 12,
  "rate_pct": 17.0
}
```

Behaviour:
- `400` if `amount_rub` > customer's `balance_rub` (insufficient funds).
- Reduce `balance_rub` by `amount_rub`.
- Record the deposit (you can reuse your products journal).
- No cashback on this operation.

Response:
```json
{
  "status": "ok",
  "client_id": "c-01000",
  "deposit_id": "d-...",
  "product": "deposit-12m",
  "amount_rub": 100000,
  "new_balance_rub": 98061,
  "matures_at": "2027-06-03",
  "ts": "..."
}
```

### POST /api/deposits/{deposit_id}/withdraw  (optional, nice to have)

Close a deposit and return principal (+ interest if matured) to `balance_rub`.
Request `{}` or `{ "early": true }`. For `deposit-flex` (early_withdrawal=true)
withdrawal is always allowed; for term deposits, early withdrawal may pay reduced
interest. Response `{status, client_id, returned_rub, new_balance_rub, ts}`.

## How to test once built

```bash
# from inside the backend container / shell, against your local port 8003
curl -s -X POST http://localhost:8003/api/deposits \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"c-01000","product":"deposit-12m","amount_rub":100000,"term_months":12,"rate_pct":17.0}'
```

Once this exists, tell me the exact path and field names and I'll wire CIB's
`POST /deposit/open` to call it, so opening a deposit truly moves the money.
Update your `CONTRACT.md` with the new endpoint so I can see it.

— CIB (Gert)
