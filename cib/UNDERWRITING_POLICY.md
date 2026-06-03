# Underwriting & Suitability Policy — CIB block

> Plain-English summary of the lending, credit-card, investment and disclosure
> rules enforced by the CIB decision engine. Intended for a compliance officer.
> The authoritative implementation is `cib/src/main.py`; this document mirrors it.
> Policy version: **2026-06-03.1** (stamped on every decision record).

## 1. Principles

- Every credit decision is made by deterministic rules. The customer-facing
  explanation is AI-generated for friendliness only and is **never** the binding
  reason — the binding basis is the deterministic `reasons` list.
- Lending is affordability-tested, not just risk-scored. We do not lend amounts a
  customer cannot service.
- A customer's **total** debt burden is considered, not each product in isolation.
- Every decision is recorded in an audit trail with its inputs and outcome.

## 2. Consumer & car loans (`POST /credit/decide`)

A loan is **declined** if any of the following is true:

1. The customer has an overdue-payment history.
2. Risk score above the threshold: 0.55 in general, relaxed to 0.65 for small
   loans (≤ 6× monthly income).
3. Monthly income below 30,000 ₽.
4. **Affordability (when an amount is supplied):** total debt-service-to-income
   (DSTI) — existing monthly debt **plus** the new loan payment — exceeds **50%**
   of income.
5. **Residual income:** less than 20,000 ₽ would remain after all debt payments.

Existing debt is read automatically from the customer record
(`existing_monthly_debt_rub`); a value may also be passed explicitly to override.

**Pricing** is risk-based: a base rate of 18.9% (consumer) / 13.9% (car),
discounted up to 4 points for low-risk customers and increased up to 3 points for
higher-risk ones. Approved customers receive a personalised rate.

**Disclosure:** every priced loan returns the monthly payment, total repayment,
total cost of credit, effective APR (monthly-compounded) and the DSTI used.

## 3. Refinancing (`POST /credit/refinance`)

Same eligibility gate as loans (overdue / risk ≤ 0.65 / income ≥ 30,000). Offers a
lower, risk-based rate and discloses the monthly and total saving. Flagged
`beneficial` only when it genuinely lowers the customer's payment.

## 4. Credit cards (`POST /card/credit-limit`)

- Standard card: risk ≤ 0.60 and income ≥ 25,000.
- Borderline customers (risk ≤ 0.72, income ≥ 18,000, no overdue history) are
  offered a **secured** card instead of an outright decline.
- Limit = income × segment multiplier × (1 − risk), **capped** at 6× monthly
  income and an absolute ceiling of 1,500,000 ₽ to contain revolving exposure.

## 5. Mortgages (`POST /mortgage/decide`)

Declined if: down payment below 20% (LTV above 80%), overdue history, risk above
0.55, income below 40,000, or total debt payments (existing debt + mortgage
payment) exceed 50% of income. Discloses monthly payment, total repayment, total
cost of credit, effective APR and DSTI.

## 6. Investment suitability (`POST /investment/suitability`, `/order-check`, `/order-plan`)

- Each customer gets an investor profile (conservative → aggressive) derived from
  time horizon (age), capacity to bear loss (income, balance) and segment —
  deliberately **not** credit risk score.
- A product is only offered if its risk level is within the customer's profile and
  the customer meets the product minimum.
- **Concentration limits** cap the share of balance in a single holding: 90% for
  low risk, 70% for mid risk, 50% for high risk — preserving an emergency buffer.
- A customer with a balance under 50,000 ₽ is restricted to the most conservative
  products only.

## 7. Audit & traceability (`GET /audit/decisions`)

Every loan, mortgage and refinance decision is logged with a unique `decision_id`,
timestamp, policy version, inputs (amount, term, risk, income), the DSTI, the
outcome and the binding reasons. Records are retrievable per customer and are also
emitted to the service logs for durable retention.

## 8. Known limitations / roadmap

- Investment suitability does not yet capture a formal knowledge/experience
  assessment or explicit risk-consent record.
- Age is used as an investment-capacity factor; documented here as a deliberate,
  risk-based choice rather than arbitrary differentiation.
- Audit records live in an in-memory buffer plus service logs; a durable store
  would strengthen long-term retention.
