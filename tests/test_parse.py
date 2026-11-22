import unittest

from scraper.parse import (
    annual_price,
    format_ram,
    format_storage,
    format_traffic,
    parse_cpu,
    parse_cycles,
    parse_disk,
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


RACKNERD_BF_PAGE = """
<div class="product-info">
    <p class="product-title">1 GB KVM VPS (Black Friday 2026)</p>
    <p>1 vCPU Core<br />
20 GB <strong>PURE SSD</strong> RAID-10 Storage<br />
1 GB RAM<br />
3000GB <strong>Monthly</strong> Premium Bandwidth<br />
1Gbps Public Network Port<br />
Full Root Admin Access</p>
</div>
<select name="billingcycle" id="inputBillingcycle" class="form-control">
    <option value="annually" selected> $15.98 USD Annually </option>
</select>
"""


# Hosteons：数字写在标签后面（`RAM: 7 GB` / `NVME Disk Space: 120 GB` / `BANDWIDTH: 7 TB`）
HOSTEONS_PAGE = """
<div class="product-info">
    <p class="product-title">RYZEN 7 GB</p>
    <p>RYZEN CPU Core (3.5 Ghz+): 6 vCore (Fair Share)<br />
RAM: 7 GB<br />
NVME Disk Space: 120 GB<br />
OS: Linux/Windows<br />
IPv4: 1<br />
IPv6: /64<br />
BANDWIDTH: 7 TB<br />
Port Speed: 1 Gbps<br />
Control Panel: YES</p>
</div>
<select name="billingcycle" id="inputBillingcycle" class="form-control">
    <option value="monthly" selected> $21.00 USD Monthly </option>
    <option value="annually" > $252.00 USD Annually </option>
</select>
"""


HOSTEONS_SPECIAL_PAGE = """
<div class="product-info">
    <p class="product-title">Special Deal 1 GB KVM SSD Gigabit VPS</p>
    <p>CPU vCore: 1 (Fair Share)<br />
RAM: 1GB<br />
SWAP: 256 MB<br />
SSD Disk Space: 15 GB<br />
OS: Linux<br />
IPv4: 1<br />
IPv6: /64<br />
BANDWIDTH: 2 TB<br />
Snapshopt: 1 Click Backup/ Snapshot Included</p>
</div>
<select name="billingcycle" id="inputBillingcycle" class="form-control">
    <option value="annually" selected> $24.00 USD Annually </option>
</select>
"""


HOSTEONS_XEON_PAGE = """
<div class="product-info">
    <p class="product-title">Dedicated Xeon VPS</p>
    <p>CPU Core: 4 (Fair Share) (Intel Xeon Gold 6148)<br />
RAM: 8 GB<br />
SSD Disk Space: 200 GB<br />
BANDWIDTH: 10TB<br />
Port Speed: Gigabit</p>
</div>
<select name="billingcycle" id="inputBillingcycle" class="form-control">
    <option value="annually" selected> $480.00 USD Annually </option>
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
        self.assertEqual(product["ram"], "1 GB")
        self.assertEqual(product["disk"], "50 GB SSD")
        self.assertEqual(product["traffic"], "1 TB")
        self.assertEqual(product["price_year"], 215.88)
        self.assertFalse(product["price_estimated"])

    def test_racknerd_black_friday_specs(self):
        product = parse_product(
            RACKNERD_BF_PAGE, 968, "https://my.racknerd.com/cart.php?a=add&pid=968",
            provider="racknerd", provider_name="RackNerd",
        )
        assert product is not None
        self.assertEqual(product["cpu"], "1 vCPU")
        self.assertEqual(product["ram"], "1 GB")
        self.assertEqual(product["disk"], "20 GB SSD")
        self.assertEqual(product["traffic"], "3 TB")
        self.assertEqual(product["price_year"], 15.98)

    def test_hosteons_ryzen_specs(self):
        product = parse_product(
            HOSTEONS_PAGE, 127, "https://my.hosteons.com/aff.php?aff=2128&pid=127",
            provider="hosteons", provider_name="Hosteons",
        )
        assert product is not None
        self.assertEqual(product["name"], "RYZEN 7 GB")
        self.assertEqual(product["cpu"], "6 vCPU")
        self.assertEqual(product["ram"], "7 GB")
        self.assertEqual(product["disk"], "120 GB NVMe")
        self.assertEqual(product["traffic"], "7 TB")
        self.assertEqual(product["price_year"], 252.0)
        self.assertEqual(product["billing_cycle"], "annually")

    def test_hosteons_special_deal_specs(self):
        product = parse_product(HOSTEONS_SPECIAL_PAGE, 110, "x",
                                provider="hosteons", provider_name="Hosteons")
        assert product is not None
        self.assertEqual(product["cpu"], "1 vCPU")
        self.assertEqual(product["ram"], "1 GB")
        self.assertEqual(product["disk"], "15 GB SSD")
        self.assertEqual(product["traffic"], "2 TB")

    def test_hosteons_labelled_xeon_specs(self):
        product = parse_product(HOSTEONS_XEON_PAGE, 130, "x",
                                provider="hosteons", provider_name="Hosteons")
        assert product is not None
        self.assertEqual(product["cpu"], "4 vCPU")
        self.assertEqual(product["cpu_model"], "Xeon Gold")
        self.assertEqual(product["ram"], "8 GB")
        self.assertEqual(product["disk"], "200 GB SSD")
        self.assertEqual(product["traffic"], "10 TB")

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
    def test_ram_unified_to_gb(self):
        # 二进制进位：1024 MB = 1 GB，不是 1.02 GB
        self.assertEqual(format_ram("1024", "MB"), "1 GB")
        self.assertEqual(format_ram("2048", "MB"), "2 GB")
        self.assertEqual(format_ram("12288", "MB"), "12 GB")
        self.assertEqual(format_ram("1", "GB"), "1 GB")
        self.assertEqual(format_ram("128", "GB"), "128 GB")

    def test_ram_below_one_gb_uses_fractions(self):
        self.assertEqual(format_ram("512", "MB"), "½ GB")
        self.assertEqual(format_ram("768", "MB"), "¾ GB")
        self.assertEqual(format_ram("256", "MB"), "¼ GB")
        self.assertEqual(format_ram("0.5", "GB"), "½ GB")

    def test_ram_keeps_decimal_at_or_above_one_gb(self):
        # >=1GB 保留小数，只去掉整数值的尾零
        self.assertEqual(format_ram("2", "GB"), "2 GB")
        self.assertEqual(format_ram("2.0", "GB"), "2 GB")
        self.assertEqual(format_ram("2.5", "GB"), "2.5 GB")
        self.assertEqual(format_ram("1.5", "GB"), "1.5 GB")

    def test_ram_tb(self):
        self.assertEqual(format_ram("1", "TB"), "1024 GB")

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
        self.assertEqual(parse_traffic("10,000GB Monthly Premium Bandwidth"), "10 TB")
        self.assertEqual(parse_traffic("20,000GB Monthly Premium Bandwidth"), "20 TB")
        self.assertEqual(parse_traffic("Unmetered Bandwidth"), "Unmetered")
        self.assertEqual(parse_traffic("1Gbps Unmetered"), "Unmetered")
        self.assertEqual(parse_traffic("1 Gbps Network Port"), "—")

    def test_disk_with_modifier_words(self):
        # RackNerd Black Friday 2026 写法：20 GB PURE SSD RAID-10 Storage
        self.assertEqual(parse_disk("20 GB PURE SSD RAID-10 Storage"), "20 GB SSD")
        self.assertEqual(parse_disk("140 GB PURE SSD RAID-10 Storage"), "140 GB SSD")
        self.assertEqual(parse_disk("1TB SATA HDD"), "1000 GB SATA")
        self.assertEqual(parse_disk("1 GB RAM"), "—")

    def test_traffic_label_style(self):
        # Hosteons 写法：数字在标签后面
        self.assertEqual(parse_traffic("BANDWIDTH: 7 TB"), "7 TB")
        self.assertEqual(parse_traffic("BANDWIDTH: 6TB"), "6 TB")
        self.assertEqual(parse_traffic("BANDWIDTH: 500 GB"), "½ TB")
        self.assertEqual(parse_traffic("Bandwidth: 10,000 GB"), "10 TB")
        self.assertEqual(parse_traffic("NETWORK: 1Gbps (Shared)"), "—")
        self.assertEqual(parse_traffic("SWAP: 256 MB"), "—")

    def test_disk_label_style(self):
        self.assertEqual(parse_disk("NVME Disk Space: 120 GB"), "120 GB NVMe")
        self.assertEqual(parse_disk("SSD Disk Space: 15 GB"), "15 GB SSD")
        self.assertEqual(parse_disk("SSD Disk Space: 1 TB"), "1000 GB SSD")

    def test_cpu_label_style(self):
        self.assertEqual(parse_cpu("CPU vCore: 1 (Fair Share)")[0], "1 vCPU")
        self.assertEqual(parse_cpu("CPU Core: 4 (Fair Share) (Intel Xeon Gold 6148)")[0], "4 vCPU")
        self.assertEqual(parse_cpu("Dedicated CPU : 8 vCore (Ryzen 5x)")[0], "8 vCPU")
        # 数字在前的写法仍然是优先的
        self.assertEqual(parse_cpu("RYZEN CPU Core (3.5 Ghz+): 6 vCore (Fair Share)")[0], "6 vCPU")


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
