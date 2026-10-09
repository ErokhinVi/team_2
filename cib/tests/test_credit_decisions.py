"""Decision boundaries and integration failures with an isolated backend double."""
import unittest
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient

from src.credit import MissingClientData, decide, monthly_payment
from src.credit_api import backend_client
from src.main import app


def customer(**changes):
    return {"id": "c1", "income_rub": 100000, "income_verified": True,
            "has_serious_current_overdue": False, "risk_level": "low",
            "is_payroll_client": False, "is_loyal_client": False, **changes}


class PolicyTests(unittest.TestCase):
    def test_rates_and_nonstacking_discounts(self):
        for risk, payroll, loyal, expected in [
            ("low", False, False, 17.9), ("standard", False, False, 24.9),
            ("low", True, False, 17.9), ("low", False, True, 14.9),
            ("low", True, True, 14.9), ("standard", True, True, 21.9)]:
            result = decide(customer(risk_level=risk, is_payroll_client=payroll,
                                     is_loyal_client=loyal), Decimal(100000), 12)
            self.assertEqual(result["decision"], "approved")
            self.assertEqual(result["personal_rate_pct"], expected)

    def test_income_boundary_uses_only_new_payment(self):
        payment = monthly_payment(Decimal(100000), Decimal("17.9"), 12)
        c = customer(income_rub=float(payment * 3), monthly_debt_payments_rub=999999)
        self.assertEqual(decide(c, Decimal(100000), 12)["decision"], "approved")
        c["income_rub"] = float(payment * 3 - Decimal("0.01"))
        self.assertEqual(decide(c, Decimal(100000), 12)["reason_code"],
                         "payment_exceeds_income_limit")

    def test_current_overdue_is_distinct_from_history(self):
        self.assertEqual(decide(customer(has_overdue_history=True), Decimal(50000), 6)
                         ["decision"], "approved")
        result = decide({"has_serious_current_overdue": True}, Decimal(50000), 6)
        self.assertEqual(result["reason_code"], "serious_current_overdue")
        self.assertIsNone(result["personal_rate_pct"])

    def test_missing_and_unverified_data_do_not_approve(self):
        for field in ["income_rub", "risk_level",
                      "has_serious_current_overdue", "is_loyal_client"]:
            c = customer(); del c[field]
            with self.assertRaises(MissingClientData):
                decide(c, Decimal(50000), 6)
        with self.assertRaises(MissingClientData):
            decide(customer(income_verified=False), Decimal(50000), 6)

    def test_backend_confirmed_income_needs_no_extra_flag(self):
        c = customer()
        del c["income_verified"]
        self.assertEqual(decide(c, Decimal(50000), 6)["decision"], "approved")

    def test_risk_threshold_and_disabled_payroll(self):
        for score, expected in [(0.041, 17.9), (0.20, 17.9), (0.200001, 24.9), (0.669, 24.9)]:
            result = decide(customer(risk_level=None, risk_score=score, is_payroll_client=None), Decimal(50000), 6)
            self.assertEqual(result["personal_rate_pct"], expected)
        for score in [float("nan"), -1, 2, True]:
            with self.assertRaises(MissingClientData):
                decide(customer(risk_score=score), Decimal(50000), 6)
        with self.assertRaises(MissingClientData):
            decide(customer(has_serious_current_overdue=None), Decimal(50000), 6)

    def test_product_bounds(self):
        for amount, term in [(49999, 6), (1500001, 60), (50000, 5), (50000, 61)]:
            with self.assertRaises(ValueError):
                decide(customer(), Decimal(amount), term)
        for amount, term in [(50000, 6), (1500000, 60)]:
            self.assertEqual(decide(customer(income_rub=1000000), Decimal(amount), term)
                             ["decision"], "approved")


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.record = {"id": "a1", "client_id": "c1", "amount_rub": 100000,
                       "term_months": 12, "status": "pending"}
        self.customer = customer()
        self.calls = []
        self.save_status = 200
        self.failure = None
        async def handler(request):
            self.calls.append((request.method, request.url.path))
            if self.failure:
                raise httpx.ConnectError("unavailable", request=request)
            if request.method == "GET" and request.url.path == "/credit-applications/a1":
                return httpx.Response(200, json=self.record)
            if request.method == "GET" and request.url.path == "/clients/c1":
                return httpx.Response(200, json=self.customer)
            if request.method == "PATCH":
                import json
                if self.save_status != 200:
                    return httpx.Response(self.save_status, json={"detail": "save failed"})
                self.record.update(json.loads(request.content), status="decided")
                return httpx.Response(200, json=self.record)
            return httpx.Response(404, json={"detail": "not found"})
        async def dependency():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                          base_url="http://backend") as client:
                yield client
        app.dependency_overrides[backend_client] = dependency
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()

    def send(self):
        return self.client.post("/credit/decide", json={"application_id": "a1"})

    def test_persist_before_success_and_repeat_returns_saved_result(self):
        first = self.send()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["decision"], "approved")
        self.assertEqual(self.record["status"], "decided")
        self.customer["income_rub"] = 0
        second = self.send()
        self.assertEqual(second.json(), first.json())
        self.assertEqual(sum(m == "PATCH" for m, _ in self.calls), 1)

    def test_missing_data_does_not_save_a_credit_rejection(self):
        del self.customer["has_serious_current_overdue"]
        response = self.send()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "client_data_incomplete")
        self.assertFalse(any(m == "PATCH" for m, _ in self.calls))

    def test_save_failure_cannot_return_approval(self):
        self.save_status = 400
        self.assertEqual(self.send().status_code, 502)
        self.assertEqual(self.record["status"], "pending")

    def test_network_failure_unknown_application_and_invalid_input(self):
        self.failure = True
        self.assertEqual(self.send().status_code, 503)
        self.failure = False
        self.assertEqual(self.client.post("/credit/decide", json={"application_id": "missing"})
                         .status_code, 404)
        for body in [{}, {"application_id": "../clients/c1"},
                     {"application_id": "a1", "income_rub": 999999}]:
            self.assertEqual(self.client.post("/credit/decide", json=body).status_code, 422)

    def test_rejection_saved_and_conflict_reported(self):
        self.customer["has_serious_current_overdue"] = True
        self.assertEqual(self.send().json()["reason_code"], "serious_current_overdue")
        self.record["status"] = "pending"
        self.save_status = 409
        self.assertEqual(self.send().status_code, 409)


if __name__ == "__main__":
    unittest.main()
