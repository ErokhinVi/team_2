import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path


class _FakeFastAPI:
    def __init__(self, **_kwargs):
        pass

    def get(self, *_args, **_kwargs):
        return lambda function: function

    def post(self, *_args, **_kwargs):
        return lambda function: function

    def patch(self, *_args, **_kwargs):
        return lambda function: function


class _FakeHTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


fake_fastapi = types.ModuleType("fastapi")
fake_fastapi.FastAPI = _FakeFastAPI
fake_fastapi.HTTPException = _FakeHTTPException
fake_fastapi.Query = lambda default=None, **_kwargs: default
sys.modules["fastapi"] = fake_fastapi

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
backend = importlib.import_module("main")


class CreditApplicationTests(unittest.TestCase):
    def setUp(self):
        if hasattr(backend, "_credit_applications"):
            backend._credit_applications.clear()
        if hasattr(backend, "_crypto_topups"):
            backend._crypto_topups.clear()

    def test_creates_pending_application_for_valid_request(self):
        result = asyncio.run(backend.create_credit_application({
            "client_id": "c-01000",
            "amount_rub": 500_000,
            "term_months": 36,
        }))

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["amount_rub"], 500_000)
        self.assertEqual(result["term_months"], 36)
        self.assertEqual(result["client_id"], "c-01000")

    def test_rejects_amount_outside_product_limits(self):
        with self.assertRaises(_FakeHTTPException) as context:
            asyncio.run(backend.create_credit_application({
                "client_id": "c-01000",
                "amount_rub": 49_999,
                "term_months": 36,
            }))

        self.assertEqual(context.exception.status_code, 400)

    def test_rejects_unknown_client(self):
        with self.assertRaises(_FakeHTTPException) as context:
            asyncio.run(backend.create_credit_application({
                "client_id": "missing",
                "amount_rub": 500_000,
                "term_months": 36,
            }))

        self.assertEqual(context.exception.status_code, 404)

    def test_cib_can_record_decision(self):
        application = asyncio.run(backend.create_credit_application({
            "client_id": "c-01000",
            "amount_rub": 500_000,
            "term_months": 36,
        }))

        result = asyncio.run(backend.record_credit_decision(
            application["id"],
            {
                "decision": "approved",
                "reason_code": "within_income_limit",
                "reason": "Платёж укладывается в лимит дохода",
                "approved_amount_rub": 500_000,
                "approved_term_months": 36,
                "personal_rate_pct": 19.9,
                "monthly_payment_rub": 18_500,
            },
        ))

        self.assertEqual(result["status"], "decided")
        self.assertEqual(result["decision"], "approved")
        self.assertEqual(result["personal_rate_pct"], 19.9)

    def test_reads_created_application(self):
        application = asyncio.run(backend.create_credit_application({
            "client_id": "c-01000",
            "amount_rub": 500_000,
            "term_months": 36,
        }))

        result = asyncio.run(backend.get_credit_application(application["id"]))

        self.assertEqual(result["id"], application["id"])
        self.assertEqual(result["status"], "pending")

    def test_accepts_rate_boundaries(self):
        for rate in (14.9, 15.9, 24.9):
            application = asyncio.run(backend.create_credit_application({
                "client_id": "c-01000",
                "amount_rub": 500_000,
                "term_months": 36,
            }))
            result = asyncio.run(backend.record_credit_decision(
                application["id"],
                {
                    "decision": "approved",
                    "reason_code": "within_income_limit",
                    "reason": "Ставка в допустимом диапазоне",
                    "approved_amount_rub": 500_000,
                    "approved_term_months": 36,
                    "personal_rate_pct": rate,
                    "monthly_payment_rub": 18_500,
                },
            ))
            self.assertEqual(result["personal_rate_pct"], rate)

    def test_rejects_rate_outside_range(self):
        for rate in (14.8, 25.0):
            application = asyncio.run(backend.create_credit_application({
                "client_id": "c-01000",
                "amount_rub": 500_000,
                "term_months": 36,
            }))
            with self.assertRaises(_FakeHTTPException) as context:
                asyncio.run(backend.record_credit_decision(
                    application["id"],
                    {
                        "decision": "approved",
                        "reason_code": "within_income_limit",
                        "reason": "Проверка ставки",
                        "approved_amount_rub": 500_000,
                        "approved_term_months": 36,
                        "personal_rate_pct": rate,
                        "monthly_payment_rub": 18_500,
                    },
                ))
            self.assertEqual(context.exception.status_code, 400)

    def test_client_credit_profile_exposes_known_and_unknown_fields(self):
        client = asyncio.run(backend.get_client("c-01000"))

        self.assertEqual(client["monthly_income_rub"], client["income_rub"])
        self.assertEqual(client["risk_level"], "standard")
        self.assertFalse(client["has_serious_current_overdue"])
        self.assertIsNone(client["is_payroll_client"])
        self.assertTrue(client["is_loyal_client"])

        higher_risk_client = asyncio.run(backend.get_client("c-01004"))
        self.assertEqual(higher_risk_client["risk_level"], "standard")
        self.assertTrue(higher_risk_client["has_serious_current_overdue"])

        low_risk_client = asyncio.run(backend.get_client("c-01013"))
        self.assertEqual(low_risk_client["risk_level"], "low")
        self.assertIsNone(low_risk_client["has_serious_current_overdue"])

    def test_repeating_same_decision_is_idempotent(self):
        application = asyncio.run(backend.create_credit_application({
            "client_id": "c-01000",
            "amount_rub": 500_000,
            "term_months": 36,
        }))
        decision = {
            "decision": "approved",
            "reason_code": "within_income_limit",
            "reason": "Платёж укладывается в лимит дохода",
            "approved_amount_rub": 500_000,
            "approved_term_months": 36,
            "personal_rate_pct": 19.9,
            "monthly_payment_rub": 18_500,
        }

        first = asyncio.run(backend.record_credit_decision(application["id"], decision))
        repeated = asyncio.run(backend.record_credit_decision(application["id"], decision))

        self.assertEqual(repeated, first)

    def test_changing_existing_decision_returns_conflict(self):
        application = asyncio.run(backend.create_credit_application({
            "client_id": "c-01000",
            "amount_rub": 500_000,
            "term_months": 36,
        }))
        approved = {
            "decision": "approved",
            "reason_code": "within_income_limit",
            "reason": "Платёж укладывается в лимит дохода",
            "approved_amount_rub": 500_000,
            "approved_term_months": 36,
            "personal_rate_pct": 19.9,
            "monthly_payment_rub": 18_500,
        }
        asyncio.run(backend.record_credit_decision(application["id"], approved))

        with self.assertRaises(_FakeHTTPException) as context:
            asyncio.run(backend.record_credit_decision(application["id"], {
                **approved,
                "decision": "rejected",
                "reason_code": "client_data_incomplete",
                "reason": "Нужны дополнительные сведения",
            }))

        self.assertEqual(context.exception.status_code, 409)

    def test_creates_demo_crypto_topup_from_cib_quote(self):
        backend._request_crypto_quote = lambda amount_rub: {
            "amount_rub": amount_rub,
            "amount_usdt": amount_rub / 100,
            "rate_rub_per_usdt": 100,
            "fee_rub": 0,
            "expires_at": "2099-01-01T00:05:00+00:00",
        }

        result = asyncio.run(backend.create_crypto_topup({
            "client_id": "c-01000",
            "amount_rub": 10_000,
        }))

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["amount_usdt"], 100)
        self.assertTrue(result["demo"])
        self.assertEqual(result["fee_rub"], 0)

    def test_rejects_crypto_topup_amount_outside_limits(self):
        with self.assertRaises(_FakeHTTPException) as context:
            asyncio.run(backend.create_crypto_topup({
                "client_id": "c-01000",
                "amount_rub": 999,
            }))

        self.assertEqual(context.exception.status_code, 400)

    def test_confirms_crypto_topup_once_and_repeat_does_not_double_credit(self):
        backend._request_crypto_quote = lambda amount_rub: {
            "amount_rub": amount_rub,
            "amount_usdt": amount_rub / 100,
            "rate_rub_per_usdt": 100,
            "fee_rub": 0,
            "expires_at": "2099-01-01T00:05:00+00:00",
        }
        topup = asyncio.run(backend.create_crypto_topup({
            "client_id": "c-01000",
            "amount_rub": 10_000,
        }))
        balance_before = backend._clients_by_id["c-01000"]["balance_rub"]

        first = asyncio.run(backend.confirm_crypto_topup(topup["id"]))
        repeated = asyncio.run(backend.confirm_crypto_topup(topup["id"]))

        self.assertEqual(first, repeated)
        self.assertEqual(
            backend._clients_by_id["c-01000"]["balance_rub"], balance_before + 10_000,
        )
        self.assertEqual(
            len([t for t in backend._transactions if t.get("crypto_topup_id") == topup["id"]]),
            1,
        )

    def test_expired_crypto_topup_is_not_credited(self):
        backend._request_crypto_quote = lambda amount_rub: {
            "amount_rub": amount_rub,
            "amount_usdt": amount_rub / 100,
            "rate_rub_per_usdt": 100,
            "fee_rub": 0,
            "expires_at": "2099-01-01T00:05:00+00:00",
        }
        topup = asyncio.run(backend.create_crypto_topup({
            "client_id": "c-01000",
            "amount_rub": 10_000,
        }))
        backend._crypto_topups[topup["id"]]["expires_at"] = "2000-01-01T00:05:00+00:00"

        with self.assertRaises(_FakeHTTPException) as context:
            asyncio.run(backend.confirm_crypto_topup(topup["id"]))

        self.assertEqual(context.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
