import unittest

from scraper.parse import (
    annual_price,
    parse_cycles,
    parse_product,
    parse_traffic,
)

PAGE = """
<div class="product-info">
    <p class="product-title">LA KVM VPS Starter</p>
    <p>1 GB RAM<br />
1x vCore CPU<br />
20 GB SSD<br />
750 GB Monthly Bandwidth<br />
1 Gbps Network Port<br />
1 IPv4</p>
</div>
<select name="billingcycle" id="inputBillingcycle" class="form-control">
    <option value="monthly" selected> $5.99 USD Monthly </option>
    <option value="annually" > $71.88 USD Annually </option>
</select>
"""


class ParseProductTest(unittest.TestCase):
    def test_basic_fields(self):
        product = parse_product(PAGE, 42, "https://example.com/cart.php?a=add&pid=42")
        self.assertIsNotNone(product)
        assert product is not None
        self.assertEqual(product["pid"], 42)
        self.assertEqual(product["name"], "LA KVM VPS Starter")
        self.assertEqual(product["cpu"], "1 vCPU")
        self.assertEqual(product["ram"], "1 GB")
        self.assertEqual(product["disk"], "20 GB SSD")
        self.assertEqual(product["traffic"], "750 GB")
        self.assertEqual(product["price_year"], 71.88)
        self.assertEqual(product["billing_cycle"], "annually")
        self.assertFalse(product["price_estimated"])

    def test_monthly_only_is_annualized(self):
        html = PAGE.replace('<option value="annually" > $71.88 USD Annually </option>', "")
        product = parse_product(html, 1, "x")
        assert product is not None
        self.assertEqual(product["price_year"], 71.88)
        self.assertTrue(product["price_estimated"])

    def test_no_product(self):
        self.assertIsNone(parse_product("<html><body>Out of Stock</body></html>", 1, "x"))


class ParseCyclesTest(unittest.TestCase):
    def test_prefers_annual(self):
        cycles = [
            {"cycle": "monthly", "price": 5.99, "label": ""},
            {"cycle": "annually", "price": 60.0, "label": ""},
        ]
        year, month, label, estimated = annual_price(cycles)
        self.assertEqual(year, 60.0)
        self.assertEqual(month, 5.0)
        self.assertEqual(label, "annually")
        self.assertFalse(estimated)

    def test_quarterly_only(self):
        cycles = [{"cycle": "quarterly", "price": 30.0, "label": ""}]
        year, _, _, estimated = annual_price(cycles)
        self.assertEqual(year, 120.0)
        self.assertTrue(estimated)

    def test_parse_select(self):
        cycles = parse_cycles(PAGE)
        self.assertEqual([c["cycle"] for c in cycles], ["monthly", "annually"])


class ParseTrafficTest(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(parse_traffic("1 TB Monthly Bandwidth"), "1 TB")
        self.assertEqual(parse_traffic("10TB Bandwidth"), "10 TB")
        self.assertEqual(parse_traffic("50TB BW"), "50 TB")
        self.assertEqual(parse_traffic("Unmetered Bandwidth"), "Unmetered")
        self.assertEqual(parse_traffic("1 Gbps Network Port"), "—")


if __name__ == "__main__":
    unittest.main()
