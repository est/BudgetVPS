import unittest

from scraper.parse import (
    annual_price,
    format_storage,
    format_traffic,
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

RACKNERD_PAGE = """
<div class="product-info">
    <p class="product-title">KVM-1GB</p>
    <p>2x vCPU Core<br />
50 GB SSD RAID-10 Storage<br />
1024MB RAM<br />
1000GB Premium Bandwidth<br />
1Gbps Network Port</p>
</div>
<select name="billingcycle" id="inputBillingcycle" class="form-control">
    <option value="monthly" selected> $17.99 USD Monthly </option>
    <option value="quarterly" > $53.97 USD Quarterly </option>
    <option value="semi-annually" > $107.94 USD Semi-Annually </option>
    <option value="annually" > $215.88 USD Annually </option>
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
        self.assertEqual(product["traffic"], "¾ TB")
        self.assertEqual(product["price_year"], 71.88)
        self.assertEqual(product["billing_cycle"], "annually")
        self.assertFalse(product["price_estimated"])

    def test_provider_fields(self):
        product = parse_product(
            PAGE, 42, "https://example.com/aff.php?aff=1033&pid=42",
            provider="dedirock", provider_name="DediRock",
        )
        assert product is not None
        self.assertEqual(product["provider"], "dedirock")
        self.assertEqual(product["provider_name"], "DediRock")
        self.assertIn("aff=1033", product["url"])

    def test_racknerd_specs(self):
        product = parse_product(RACKNERD_PAGE, 20, "https://my.racknerd.com/x",
                                provider="racknerd", provider_name="RackNerd")
        assert product is not None
        self.assertEqual(product["cpu"], "2 vCPU")
        self.assertEqual(product["ram"], "1024 MB")
        self.assertEqual(product["disk"], "50 GB SSD")
        self.assertEqual(product["traffic"], "1 TB")
        self.assertEqual(product["price_year"], 215.88)
        self.assertFalse(product["price_estimated"])

    def test_monthly_only_is_annualized(self):
        html = PAGE.replace('<option value="annually" > $71.88 USD Annually </option>', "")
        product = parse_product(html, 1, "x")
        assert product is not None
        self.assertEqual(product["price_year"], 71.88)
        self.assertTrue(product["price_estimated"])

    def test_model_only_cpu(self):
        html = """
        <div class="product-info">
            <p class="product-title">Xeon VPS</p>
            <p>Intel Xeon E3-1230 V1 (or higher)<br />16 GB RAM<br />1TB SATA HDD<br />
            10 TB Monthly Transfer</p>
        </div>
        <select name="billingcycle"><option value="annually">$100 USD Annually</option></select>
        """
        product = parse_product(html, 1, "x")
        assert product is not None
        self.assertEqual(product["cpu"], "Xeon E3-1230 V1")
        self.assertEqual(product["disk"], "1000 GB SATA")
        self.assertEqual(product["traffic"], "10 TB")

    def test_single_disk_no_multiplier(self):
        html = """
        <div class="product-info">
            <p class="product-title">VPS</p>
            <p>1x 960GB SSD<br />1Gbps Unmetered</p>
        </div>
        """
        product = parse_product(html, 1, "x")
        assert product is not None
        self.assertEqual(product["disk"], "960 GB SSD")
        self.assertEqual(product["traffic"], "Unmetered")

    def test_fallback_to_name_when_specs_empty(self):
        html = """
        <div class="product-info">
            <p class="product-title">AMD Ryzen 3950X | 128GB RAM | 1.2 TB NVMe SSD</p>
            <p></p>
        </div>
        <select name="billingcycle"><option value="annually">$3168 USD Annually</option></select>
        """
        product = parse_product(html, 1, "x")
        assert product is not None
        self.assertEqual(product["cpu"], "Ryzen 3950X")
        self.assertEqual(product["ram"], "128 GB")
        self.assertEqual(product["disk"], "1200 GB NVMe")
        self.assertEqual(product["traffic"], "—")

    def test_no_product(self):
        self.assertIsNone(parse_product("<html><body>Out of Stock</body></html>", 1, "x"))


class UnitTest(unittest.TestCase):
    def test_storage_gb(self):
        self.assertEqual(format_storage("1", "TB"), "1000 GB")
        self.assertEqual(format_storage("2", "TB"), "2000 GB")
        self.assertEqual(format_storage("512", "MB"), "0.51 GB")
        self.assertEqual(format_storage("2.5", "TB"), "2500 GB")

    def test_traffic_fractions(self):
        self.assertEqual(format_traffic("750", "GB"), "¾ TB")
        self.assertEqual(format_traffic("500", "GB"), "½ TB")
        self.assertEqual(format_traffic("250", "GB"), "¼ TB")
        self.assertEqual(format_traffic("125", "GB"), "⅛ TB")
        self.assertEqual(format_traffic("1500", "GB"), "1½ TB")
        self.assertEqual(format_traffic("100", "GB"), "0.1 TB")
        self.assertEqual(format_traffic("110", "GB"), "0.11 TB")
        self.assertEqual(format_traffic("1000", "GB"), "1 TB")
        self.assertEqual(format_traffic("5", "TB"), "5 TB")
        self.assertEqual(format_traffic("35", "TB"), "35 TB")

    def test_traffic_variants(self):
        self.assertEqual(parse_traffic("1 TB Monthly Bandwidth"), "1 TB")
        self.assertEqual(parse_traffic("10TB Bandwidth"), "10 TB")
        self.assertEqual(parse_traffic("50TB BW"), "50 TB")
        self.assertEqual(parse_traffic("1000GB Premium Bandwidth"), "1 TB")
        self.assertEqual(parse_traffic("Unmetered Bandwidth"), "Unmetered")
        self.assertEqual(parse_traffic("1Gbps Unmetered"), "Unmetered")
        self.assertEqual(parse_traffic("1 Gbps Network Port"), "—")


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


if __name__ == "__main__":
    unittest.main()
