"""Checks for payment arithmetic and existing product behavior."""
import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from src.credit import monthly_payment
from src.main import app


class CreditPreparationTests(unittest.TestCase):
    def test_payment_matches_independent_float_formula(self):
        for amount, rate, term in [(50000, 17.9, 6), (1500000, 24.9, 60), (300000, 17.9, 24)]:
            r = rate / 1200
            expected = amount * r * (1 + r) ** term / ((1 + r) ** term - 1)
            actual = monthly_payment(Decimal(amount), Decimal(str(rate)), term)
            self.assertAlmostEqual(float(actual), expected, delta=0.0051)

    def test_zero_rate_and_invalid_values(self):
        self.assertEqual(monthly_payment(Decimal(60000), Decimal(0), 12), Decimal("5000.00"))
        for amount, rate, term in [("0", "17.9", 6), ("NaN", "17.9", 6),
                                   ("50000", "Infinity", 6), ("50000", "-1", 6),
                                   ("50000", "17.9", 0), ("50000", "17.9", True)]:
            with self.assertRaises(ValueError):
                monthly_payment(Decimal(amount), Decimal(rate), term)

    def test_catalog_retains_existing_products_and_marks_credit_unavailable(self):
        with TestClient(app) as client:
            response = client.get("/products")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["total"], 3)
            products = {p["id"]: p for p in body["items"]}
            self.assertIn("card-debit", products)
            self.assertEqual(products["deposit-base"]["rate_pct"], 14.0)
            self.assertFalse(products["credit-consumer"]["application_available"])
            self.assertIn("Потребительский кредит", client.get("/").text)
            self.assertEqual(client.get("/health").json()["products"], 3)


if __name__ == "__main__":
    unittest.main()
