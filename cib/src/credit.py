"""Deterministic annuity calculation, independent of pending credit policy."""
from decimal import Decimal, ROUND_HALF_UP
import math

POLICY_VERSION = "consumer-2026-10-09-v2"


class MissingClientData(ValueError):
    def __init__(self, fields):
        self.fields = fields
        super().__init__("Client data is missing or invalid")


def client_terms(client: dict) -> tuple[Decimal, Decimal]:
    required_flags = ["has_serious_current_overdue",
                      "is_loyal_client"]
    missing = [key for key in required_flags if type(client.get(key)) is not bool]
    # Backend confirms income_rub is verified monthly income; honor an explicit contrary flag.
    if "income_verified" in client and client["income_verified"] is not True:
        missing.append("income_verified")
    income = client.get("income_rub")
    if type(income) not in (int, float) or not math.isfinite(income) or income < 0:
        missing.append("income_rub")
    risk = client.get("risk_level")
    if client.get("risk_score") is not None:
        score = client["risk_score"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            missing.append("risk_score")
        else:
            risk = "low" if Decimal(str(score)) <= Decimal("0.20") else "standard"
    if risk not in ("low", "standard"):
        missing.append("risk_level")
    if missing:
        raise MissingClientData(sorted(set(missing)))
    base = Decimal("17.9") if risk == "low" else Decimal("24.9")
    # Payroll discounts are explicitly disabled for this first version.
    discount = Decimal(3) if client["is_loyal_client"] else Decimal(0)
    return Decimal(str(income)), base - discount


def decide(client: dict, amount: Decimal, term: int) -> dict:
    if not amount.is_finite() or not Decimal(50000) <= amount <= Decimal(1500000):
        raise ValueError("Amount outside product limits")
    if type(term) is not int or not 6 <= term <= 60:
        raise ValueError("Term outside product limits")
    result = dict(decision="rejected", reason_code="", reason="",
                  approved_amount_rub=0, approved_term_months=None,
                  personal_rate_pct=None, monthly_payment_rub=None)
    if client.get("has_serious_current_overdue") is True:
        result.update(reason_code="serious_current_overdue",
                      reason="Есть серьёзная действующая просрочка")
        return result
    income, rate = client_terms(client)
    payment = monthly_payment(amount, rate, term)
    if payment * 3 > income:
        result.update(reason_code="payment_exceeds_income_limit",
                      reason="Новый платёж превышает треть подтверждённого месячного дохода")
        return result
    result.update(decision="approved", reason_code="approved",
                  reason="Заявка соответствует условиям продукта",
                  approved_amount_rub=float(amount), approved_term_months=term,
                  personal_rate_pct=float(rate), monthly_payment_rub=float(payment))
    return result


def monthly_payment(amount_rub: Decimal, annual_rate_pct: Decimal, term_months: int) -> Decimal:
    """Return a fixed monthly payment rounded to kopecks; no fees included."""
    if not amount_rub.is_finite() or amount_rub <= 0:
        raise ValueError("Amount must be finite and positive")
    if not annual_rate_pct.is_finite() or annual_rate_pct < 0:
        raise ValueError("Rate must be finite and nonnegative")
    if isinstance(term_months, bool) or not isinstance(term_months, int) or term_months <= 0:
        raise ValueError("Term must be a positive integer")
    rate = annual_rate_pct / Decimal(1200)
    if rate == 0:
        payment = amount_rub / term_months
    else:
        payment = amount_rub * rate / (1 - (1 + rate) ** (-term_months))
    return payment.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
