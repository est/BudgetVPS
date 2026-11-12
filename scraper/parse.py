"""WHMCS 产品页解析。

WHMCS 的 cart.php?a=add&pid=N 大致有三种结果：
  1. 200 + 配置页  -> 有货，能拿到名称 / 配置 / 价格
  2. 跳转到 /index.php/store/<分类>/<slug> 且页面带 "Out of Stock" -> 售罄
  3. 跳转到 /index.php/store/<分类> -> pid 不存在（或已下架）
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
CPU_MODEL_RE = re.compile(
    r"\b((?:e[35]-\d{4,5}\s?v?\d?|i[3579]-\d{4,5}\w*|ryzen\s+\d\s+\w+|epyc\s+\w+"
    r"|xeon\s+\w+[\w-]*|apple\s+m\d\w*))\b",
    re.I,
)
RAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|MB|TB)\s*(?:of\s+)?(?:RAM|DDR\d?)", re.I)
RAM_ALT_RE = re.compile(r"(?:RAM|DDR\d?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(GB|MB|TB)", re.I)
DISK_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(GB|TB|MB)\s*(?:of\s+)?"
    r"(SSD|NVME|NVMe|HDD|SAS|SATA|Storage|Disk|Space)\b",
    re.I,
)
DISK_MULTI_RE = re.compile(
    r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(TB|GB)\s*"
    r"(SSD|NVME|NVMe|HDD|SAS|SATA)\b",
    re.I,
)
TRAFFIC_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)\s*(?:of\s+)?"
    r"(?:(?:monthly|daily|weekly|annual|annually|yearly)\s+)?"
    r"(?:Bandwidth|Traffic|Transfer|BW)\b",
    re.I,
)
TRAFFIC_UNMETERED_RE = re.compile(r"unmetered\s+(?:bandwidth|traffic|transfer)", re.I)


def clean_text(value: str) -> str:
    value = html_lib.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_product(html: str, pid: int, url: str) -> dict[str, Any] | None:
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

    specs_text = " | ".join(lines)
    cpu, cpu_model = parse_cpu(specs_text)
    ram = parse_ram(specs_text)
    disk = parse_disk(specs_text)
    traffic = parse_traffic(specs_text)
    cycles = parse_cycles(html)
    price_year, price_month, cycle_label, estimated = annual_price(cycles)

    return {
        "pid": pid,
        "name": name,
        "cpu": cpu,
        "cpu_model": cpu_model,
        "ram": ram,
        "disk": disk,
        "traffic": traffic,
        "price_year": price_year,
        "price_month": price_month,
        "billing_cycle": cycle_label,
        "price_estimated": estimated,
        "currency": "USD",
        "url": url,
        "specs_raw": lines,
    }


def parse_cpu(text: str) -> tuple[str, str]:
    cores = CPU_RE.search(text)
    model = CPU_MODEL_RE.search(text)
    if cores:
        return f"{cores.group(1)} vCPU", model.group(1) if model else ""
    ghz = CPU_GHZ_RE.search(text)
    if ghz:
        return f"{ghz.group(1)} vCPU", model.group(1) if model else ""
    if model:
        return "—", model.group(1)
    return "—", ""


def parse_ram(text: str) -> str:
    match = RAM_RE.search(text) or RAM_ALT_RE.search(text)
    if match:
        return f"{match.group(1)} {match.group(2).upper()}"
    return "—"


def parse_disk(text: str) -> str:
    multi = DISK_MULTI_RE.search(text)
    if multi:
        kind = multi.group(4).upper().replace("NVME", "NVMe")
        return f"{multi.group(1)} × {multi.group(2)} {multi.group(3).upper()} {kind}"
    match = DISK_RE.search(text)
    if match:
        kind = match.group(3).upper().replace("NVME", "NVMe")
        if kind in ("STORAGE", "DISK", "SPACE"):
            kind = ""
        return f"{match.group(1)} {match.group(2).upper()} {kind}".strip()
    return "—"


def parse_traffic(text: str) -> str:
    match = TRAFFIC_RE.search(text)
    if match:
        return f"{match.group(1)} {match.group(2).upper()}"
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

    # 其他周期（季付/半年付/两年付…）折算成年价
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
    return "Out of Stock" in html or "out of stock" in html.lower()


def looks_like_product(html: str) -> bool:
    return 'class="product-title"' in html and "<div" in html
