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
        self.assertIsNone(client["risk_level"])
        self.assertIsNone(client["has_serious_current_overdue"])
        self.assertIsNone(client["is_payroll_client"])
        self.assertTrue(client["is_loyal_client"])


if __name__ == "__main__":
    unittest.main()
