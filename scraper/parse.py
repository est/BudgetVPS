"""WHMCS 产品页解析。

WHMCS 的 cart.php?a=add&pid=N 大致有三种结果：
  1. 200 + 配置页  -> 有货，能拿到名称 / 配置 / 价格
  2. 跳转到 /index.php/store/<分类>/<slug> 且页面带 "Out of Stock" -> 售罄
  3. 跳转到 /index.php/store/<分类> -> pid 不存在（或已下架）

为什么不直接走 WHMCS API：
  * includes/api.php 的 GetProducts 需要管理员 API key + IP 白名单；
  * feeds/productsinfo.php?get=description 是公开的，但 racknerd 整个 /feeds/
    被 LiteSpeed 403（dedirock 可用），所以仍以购物车页 HTML 为准。

展示口径：
  * Storage 一律换算成 GB（1 TB = 1000 GB，硬盘厂的十进制标称）
  * RAM 一律换算成 GB（1024 MB = 1 GB，内存的二进制进位）
    这样 512 MB / 768 MB / 1024 MB 才能落成 ½ / ¾ / 1，而不是 0.51 / 0.77 / 1.02
  * Traffic 一律换算成 TB，能写成 ¼ ½ ¾ 的就写分数，否则保留两位小数
  * 分数写法全站统一：能落成 ¼ ½ ¾ 这类的就用 unicode 分数，整数不带小数点（2.0 -> 2）
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Any

CYCLE_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semiannually": 6,
    "semi-annually": 6,
    "annually": 12,
    "annual": 12,
    "biennially": 24,
    "triennially": 36,
}

CPU_RE = re.compile(r"(\d+)\s*(?:x\s*)?(?:v?cores?|v?cpus?)\b", re.I)
CPU_GHZ_RE = re.compile(r"(\d+)\s*x\s*[\d.]+\s*GHz", re.I)
# 有的商家把数字写在标签后面：`CPU vCore: 1 (Fair Share)` / `CPU Core: 4`
# / `Dedicated CPU : 8 vCore`
CPU_LABEL_RE = re.compile(r"\b(?:v?CPU|v?Core)s?\s*(?:Core|Cores)?\s*[:=]\s*(\d+)\b", re.I)
CPU_MODEL_RE = re.compile(
    r"\b((?:e[35]-\d{4,5}\s?v?\d?|i[3579]-\d{4,5}\w*"
    r"|ryzen\s+\d{1,2}\s*(?!(?:GB|TB|MB)\b)\w+|epyc\s+\w+"
    r"|xeon\s+(?:e[35]-\d{4,5}\s*v?\d?|\w+[\w-]*)|apple\s+m\d\w*))\b",
    re.I,
)
RAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|MB|TB)\s*(?:of\s+)?(?:RAM|DDR\d?)", re.I)
RAM_ALT_RE = re.compile(r"(?:RAM|DDR\d?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(GB|MB|TB)", re.I)
DISK_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(GB|TB|MB)\s+(?:of\s+)?"
    r"(?:[A-Za-z][\w-]*\s+){0,4}?"
    r"(SSD|NVME|NVMe|HDD|SAS|SATA|Storage|Disk|Space)\b",
    re.I,
)
DISK_MULTI_RE = re.compile(
    r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(TB|GB)\s*"
    r"(SSD|NVME|NVMe|HDD|SAS|SATA)\b",
    re.I,
)
# 数字写在标签后面：`NVME Disk Space: 120 GB` / `SSD Disk Space: 15 GB`
DISK_LABEL_RE = re.compile(
    r"\b(SSD|NVME|NVMe|HDD|SAS|SATA)\s+(?:Disk|Storage)\s+Space\s*[:=]\s*"
    r"(\d+(?:\.\d+)?)\s*(GB|TB|MB)\b",
    re.I,
)
TRAFFIC_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(TB|GB|MB)\s+"
    r"(?:[A-Za-z][A-Za-z-]*\s+){0,3}"
    r"(?:Bandwidth|Traffic|Transfer|BW)\b",
    re.I,
)
# 数字写在标签后面：`BANDWIDTH: 7 TB` / `BANDWIDTH: 6TB`
TRAFFIC_LABEL_RE = re.compile(
    r"\b(?:Bandwidth|Transfer|Traffic|BW)\s*[:=]\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*(TB|GB|MB)\b",
    re.I,
)
TRAFFIC_UNMETERED_RE = re.compile(r"unmetered\b", re.I)

FRACTIONS = (
    (1 / 8, "⅛"),
    (1 / 4, "¼"),
    (1 / 3, "⅓"),
    (3 / 8, "⅜"),
    (1 / 2, "½"),
    (5 / 8, "⅝"),
    (2 / 3, "⅔"),
    (3 / 4, "¾"),
    (7 / 8, "⅞"),
)


def clean_text(value: str) -> str:
    value = html_lib.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _to_gb(size: str, unit: str) -> float:
    value = float(size.replace(",", ""))
    unit = unit.upper()
    if unit == "MB":
        return value / 1000
    if unit == "TB":
        return value * 1000
    return value


def _to_gb_binary(size: str, unit: str) -> float:
    """内存用二进制进位：1024 MB = 1 GB。"""
    value = float(size.replace(",", ""))
    unit = unit.upper()
    if unit == "MB":
        return value / 1024
    if unit == "TB":
        return value * 1024
    return value


def _fraction_text(value: float) -> str | None:
    whole = int(value)
    remainder = value - whole
    for fraction, glyph in FRACTIONS:
        if abs(remainder - fraction) < 0.002:
            return f"{whole if whole else ''}{glyph}"
    return None


def format_storage(size: str, unit: str) -> str:
    return f"{_fmt_num(_to_gb(size, unit))} GB"


def format_ram(size: str, unit: str) -> str:
    """RAM 统一成 GB。

    * < 1 GB：能落成 ¼ ½ ¾ 这类的用 unicode 分数（512 MB -> ½ GB）
    * >= 1 GB：保留小数，只把 2.0 这种整数值的尾零去掉（2.0 -> 2，2.5 -> 2.5）
    """
    gb = _to_gb_binary(size, unit)
    if gb < 1:
        fraction = _fraction_text(gb)
        if fraction:
            return f"{fraction} GB"
    return f"{_fmt_num(gb)} GB"


def format_traffic(size: str, unit: str) -> str:
    tb = _to_gb(size, unit) / 1000
    fraction = _fraction_text(tb)
    if fraction:
        return f"{fraction} TB"
    return f"{_fmt_num(tb)} TB"


def parse_product(
    html: str,
    pid: int,
    url: str,
    provider: str = "",
    provider_name: str = "",
) -> dict[str, Any] | None:
    info = re.search(r'<div class="product-info">(.*?)</div>', html, re.S)
    if not info:
        return None

    block = info.group(1)
    name_match = re.search(r'<p class="product-title">(.*?)</p>', block, re.S)
    name = clean_text(name_match.group(1)) if name_match else ""
    if not name:
        return None

    body = re.sub(r'<p class="product-title">.*?</p>', "", block, flags=re.S)
    lines = [clean_text(part) for part in re.split(r"<br\s*/?>", body)]
    lines = [line for line in lines if line]

    return build_product(
        pid, name, lines, parse_cycles(html), url, provider, provider_name
    )


def build_product(
    pid: int,
    name: str,
    specs_lines: list[str],
    cycles: list[dict[str, Any]],
    url: str,
    provider: str = "",
    provider_name: str = "",
) -> dict[str, Any]:
    """用已经拿到的名称 / 规格行 / 计费周期组装成统一的产品结构。"""
    # 有些可配置产品页的 product-info 是空的，规格全写在标题里，这时退回解析标题
    specs_text = " | ".join(specs_lines) or name
    cpu, cpu_model = parse_cpu(specs_text)
    price_year, price_month, cycle_label, estimated = annual_price(cycles)

    return {
        "pid": pid,
        "provider": provider,
        "provider_name": provider_name,
        "name": name,
        "cpu": cpu,
        "cpu_model": cpu_model,
        "ram": parse_ram(specs_text),
        "disk": parse_disk(specs_text),
        "traffic": parse_traffic(specs_text),
        "price_year": price_year,
        "price_month": price_month,
        "billing_cycle": cycle_label,
        "price_estimated": estimated,
        "currency": "USD",
        "url": url,
        "specs_raw": specs_lines,
    }


def parse_cpu(text: str) -> tuple[str, str]:
    cores = CPU_RE.search(text)
    model = CPU_MODEL_RE.search(text)
    if cores:
        return f"{cores.group(1)} vCPU", model.group(1) if model else ""
    labelled = CPU_LABEL_RE.search(text)
    if labelled:
        return f"{labelled.group(1)} vCPU", model.group(1) if model else ""
    ghz = CPU_GHZ_RE.search(text)
    if ghz:
        return f"{ghz.group(1)} vCPU", model.group(1) if model else ""
    if model:
        return model.group(1), model.group(1)
    return "—", ""


def parse_ram(text: str) -> str:
    match = RAM_RE.search(text) or RAM_ALT_RE.search(text)
    if match:
        return format_ram(match.group(1), match.group(2))
    return "—"


def parse_disk(text: str) -> str:
    multi = DISK_MULTI_RE.search(text)
    if multi:
        kind = multi.group(4).upper().replace("NVME", "NVMe")
        size = format_storage(multi.group(2), multi.group(3))
        count = multi.group(1)
        prefix = "" if count == "1" else f"{count} × "
        return f"{prefix}{size} {kind}"
    labelled = DISK_LABEL_RE.search(text)
    if labelled:
        kind = labelled.group(1).upper().replace("NVME", "NVMe")
        size = format_storage(labelled.group(2), labelled.group(3))
        return f"{size} {kind}".strip()
    match = DISK_RE.search(text)
    if match:
        kind = match.group(3).upper().replace("NVME", "NVMe")
        if kind in ("STORAGE", "DISK", "SPACE"):
            kind = ""
        return f"{format_storage(match.group(1), match.group(2))} {kind}".strip()
    return "—"


def parse_traffic(text: str) -> str:
    match = TRAFFIC_LABEL_RE.search(text) or TRAFFIC_RE.search(text)
    if match:
        return format_traffic(match.group(1), match.group(2))
    if TRAFFIC_UNMETERED_RE.search(text):
        return "Unmetered"
    return "—"


def parse_cycles(html: str) -> list[dict[str, Any]]:
    select = re.search(
        r'<select[^>]*name="billingcycle"[^>]*>(.*?)</select>', html, re.S | re.I
    )
    if not select:
        return []

    cycles: list[dict[str, Any]] = []
    for value, text in re.findall(
        r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', select.group(1), re.S
    ):
        label = clean_text(text)
        price = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", label)
        if not price:
            continue
        cycles.append(
            {
                "cycle": value.lower().strip(),
                "price": float(price.group(1).replace(",", "")),
                "label": label,
            }
        )
    return cycles


def annual_price(
    cycles: list[dict[str, Any]],
) -> tuple[float | None, float | None, str, bool]:
    """返回 (年价, 月价, 计费周期说明, 年价是否为按月估算)。"""
    if not cycles:
        return None, None, "—", False

    by_cycle = {c["cycle"]: c for c in cycles}

    annual = by_cycle.get("annually") or by_cycle.get("annual")
    if annual:
        year = annual["price"]
        return year, round(year / 12, 2), "annually", False

    monthly = by_cycle.get("monthly")
    if monthly:
        year = monthly["price"] * 12
        return round(year, 2), monthly["price"], "monthly", True

    best = None
    for cycle in cycles:
        months = CYCLE_MONTHS.get(cycle["cycle"])
        if months:
            year = cycle["price"] * 12 / months
            if best is None or year < best[0]:
                best = (year, cycle)
    if best:
        year, cycle = best
        return round(year, 2), round(year / 12, 2), cycle["cycle"], True

    return None, None, "—", False


def is_out_of_stock(html: str) -> bool:
    return "out of stock" in html.lower()


def looks_like_product(html: str) -> bool:
    return 'class="product-title"' in html and "<div" in html
