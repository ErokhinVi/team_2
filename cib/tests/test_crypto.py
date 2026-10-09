import unittest
from datetime import datetime
from fastapi.testclient import TestClient
from src.main import app


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_exact_conversion_and_expiry(self):
        for amount, expected in [("1000", "10.000000"), ("100000", "1000.000000"),
                                 ("1234.56", "12.345600")]:
            r = self.client.post("/crypto/quote", json={"amount_rub": amount})
            self.assertEqual(r.status_code, 200)
            d = r.json()
            self.assertEqual(d["crypto_amount"], expected)
            self.assertEqual(d["credit_amount_rub"], d["amount_rub"])
            self.assertEqual(d["fee_rub"], "0.00")
            self.assertEqual((datetime.fromisoformat(d["expires_at"]) -
                              datetime.fromisoformat(d["created_at"])).total_seconds(), 300)

    def test_invalid_amounts_and_unsupported_assets(self):
        for amount in ["999.99", "100000.01", "1000.001", "NaN", "Infinity", -1, True]:
            self.assertEqual(self.client.post("/crypto/quote", json={"amount_rub": amount}).status_code, 422)
        for extra in [{"asset": "BTC"}, {"rate_rub_per_unit": 1}, {"mode": "live"}]:
            self.assertEqual(self.client.post("/crypto/quote", json={"amount_rub": 1000, **extra}).status_code, 422)

    def test_demo_cannot_claim_payment_or_generate_address(self):
        d = self.client.post("/crypto/quote", json={"amount_rub": 1000}).json()
        self.assertTrue(d["demo_only"])
        self.assertFalse(d["can_accept_payment"])
        self.assertEqual(d["status"], "preview")
        self.assertNotIn("wallet_address", d)
        self.assertEqual(d["rate_source"], "fixed_demo_not_market")
        self.assertIn("реальные переводы не принимаются", self.client.get("/crypto/demo").text)

    def test_catalog_exposes_preview_only(self):
        products = self.client.get("/products").json()["items"]
        crypto = next(x for x in products if x["id"] == "crypto-topup-demo")
        self.assertTrue(crypto["preview_available"])
        self.assertFalse(crypto["application_available"])
