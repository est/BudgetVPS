"""按 pid 顺序扫描 WHMCS 产品。"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cf import get_credentials
from .fetch import ChallengeError, Fetcher
from .parse import is_out_of_stock, parse_product


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CrawlStats:
    scanned: int = 0
    active: int = 0
    out_of_stock: int = 0
    missing: int = 0
    errors: int = 0
    challenges: int = 0
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""


@dataclass
class CrawlResult:
    found: dict[str, Any] = field(default_factory=dict)
    out_of_stock: set[str] = field(default_factory=set)
    stats: CrawlStats = field(default_factory=CrawlStats)


def load_store(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        if isinstance(data.get("products"), dict):
            return data
    except Exception:
        pass
    return {"products": {}}


def crawl(
    base_url: str,
    min_pid: int,
    max_pid: int,
    delay_min: float,
    delay_max: float,
    credentials: dict[str, Any],
    cookie_cache: Path,
) -> CrawlResult:
    fetcher = Fetcher(base_url, credentials)
    result = CrawlResult()
    stats = result.stats

    for pid in range(min_pid, max_pid + 1):
        stats.scanned += 1
        key = str(pid)
        resp = None
        challenge_retries = 0

        while True:
            try:
                resp = fetcher.get(f"/cart.php?a=add&pid={pid}")
                break
            except ChallengeError:
                stats.challenges += 1
                challenge_retries += 1
                if challenge_retries > 2:
                    stats.errors += 1
                    print(f"[{pid}] Cloudflare 验证反复失败，跳过", flush=True)
                    break
                print(f"[{pid}] 触发 Cloudflare 验证，重新取 cookie…", flush=True)
                credentials = get_credentials(
                    base_url, cookie_cache, max_age=0, force=True
                )
                fetcher.update_credentials(credentials)
            except Exception as exc:  # noqa: BLE001
                stats.errors += 1
                print(f"[{pid}] 请求失败: {exc}", flush=True)
                time.sleep(8)
                break

        if resp is None:
            time.sleep(random.uniform(delay_min, delay_max))
            continue

        product = parse_product(
            resp.text, pid, f"{base_url.rstrip('/')}/cart.php?a=add&pid={pid}"
        )
        if product:
            product["status"] = "active"
            product["last_seen"] = utc_now()
            product["final_url"] = resp.url
            result.found[key] = product
            price = product.get("price_year")
            price_text = f"${price:,.2f}" if price is not None else "—"
            print(
                f"[{pid}] ✓ {product['name']}  "
                f"{product['cpu']} / {product['ram']} / {product['disk']} / "
                f"{product['traffic']} / {price_text}/yr",
                flush=True,
            )
        elif is_out_of_stock(resp.text):
            result.out_of_stock.add(key)
            print(f"[{pid}] 售罄", flush=True)
        else:
            print(f"[{pid}] 无产品", flush=True)

        time.sleep(random.uniform(delay_min, delay_max))

    stats.active = len(result.found)
    stats.out_of_stock = len(result.out_of_stock)
    stats.missing = max(
        0, stats.scanned - stats.active - stats.out_of_stock - stats.errors
    )
    stats.finished_at = utc_now()
    return result


def merge_store(
    previous: dict[str, Any],
    result: CrawlResult,
) -> dict[str, Any]:
    """把本次结果并入历史库：没扫到的旧产品保留数据，只更新状态。"""
    products: dict[str, Any] = dict(previous.get("products", {}))
    now = utc_now()

    for key, product in result.found.items():
        old = products.get(key, {})
        product.setdefault("first_seen", old.get("first_seen", now))
        products[key] = product

    for key, product in products.items():
        if key in result.found:
            continue
        product["status"] = (
            "out_of_stock" if key in result.out_of_stock else "stale"
        )

    return {"products": products}
