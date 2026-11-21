"""按 pid 顺序扫描 WHMCS 产品。

支持"采不完就下次接着采"：
  * crawl() 接收一个 deadline，到点就收工，已采到的数据照常返回（complete=False）
  * 每个站点在 ndjson 里记一条 progress（下次从哪个 pid 继续 / 这一轮采完没有）
  * merge_store() 只更新**这一轮真正请求过**的 pid 状态，半途中断不会把没扫到的
    商品误标成 stale
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .cf import get_credentials
from .fetch import ChallengeError, Fetcher
from .parse import is_out_of_stock, parse_product
from .sites import Site


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CrawlStats:
    scanned: int = 0
    skipped: int = 0
    active: int = 0
    out_of_stock: int = 0
    missing: int = 0
    errors: int = 0
    challenges: int = 0
    incomplete: bool = False
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""


@dataclass
class CrawlResult:
    found: dict[str, Any] = field(default_factory=dict)
    out_of_stock: set[str] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)
    visited: set[str] = field(default_factory=set)
    stats: CrawlStats = field(default_factory=CrawlStats)
    min_pid: int = 1
    max_pid: int = 0
    next_pid: int = 1
    complete: bool = True


def load_store(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        if isinstance(data.get("products"), dict):
            return data
    except Exception:
        pass
    return {"products": {}, "missing": []}


def _last_known_pid(products: dict[str, Any]) -> int:
    """最后一个"存在过"的 pid（在售或售罄），用于判断尾部要复查的范围。"""
    pids = [
        int(pid)
        for pid, product in products.items()
        if product.get("status") in ("active", "out_of_stock")
    ]
    return max(pids, default=0)


def resume_pid(previous: dict[str, Any], min_pid: int, max_pid: int) -> int:
    """上一轮没采完就从游标继续；采完了（或没有游标）就从 min_pid 重新采。"""
    progress = previous.get("progress") or {}
    if progress and not progress.get("complete", True):
        try:
            cursor = int(progress.get("next_pid"))
        except (TypeError, ValueError):
            return min_pid
        return max(min_pid, min(cursor, max_pid))
    return min_pid


def crawl(
    site: Site,
    min_pid: int,
    max_pid: int,
    delay_min: float,
    delay_max: float,
    credentials: dict[str, Any],
    cookie_cache: Path,
    previous: dict[str, Any] | None = None,
    deadline: float | None = None,
    on_checkpoint: Callable[[CrawlResult], None] | None = None,
    checkpoint_every: int = 25,
) -> CrawlResult:
    previous = previous or {}
    fetcher = Fetcher(site.base_url, credentials)
    result = CrawlResult(min_pid=min_pid, max_pid=max_pid)
    stats = result.stats

    # 上次确认"无产品"的 pid：中间的空洞直接跳过；尾部（最后一个已知 pid 之后）仍然复查
    previous_missing = {str(pid) for pid in previous.get("missing") or []}
    last_known = _last_known_pid(previous.get("products") or {})
    result.missing = set(previous_missing)

    start_pid = resume_pid(previous, min_pid, max_pid)
    result.next_pid = start_pid
    if start_pid > min_pid:
        print(
            f"[main] {site.id}：上一轮没采完，从 pid {start_pid} 继续（到 {max_pid}）",
            flush=True,
        )

    for pid in range(start_pid, max_pid + 1):
        if deadline is not None and time.monotonic() >= deadline:
            result.complete = False
            result.next_pid = pid
            print(
                f"[main] {site.id}：到达时间预算，停在 pid {pid}"
                f"（本轮已请求 {stats.scanned} 个），下轮从这里继续",
                flush=True,
            )
            break

        key = str(pid)
        if key in previous_missing and pid < last_known:
            stats.skipped += 1
            continue

        if on_checkpoint and stats.scanned and stats.scanned % checkpoint_every == 0:
            _checkpoint(on_checkpoint, result, site, stats)

        stats.scanned += 1
        resp = None
        challenge_retries = 0
        path = site.crawl_path.format(pid=pid)

        while True:
            try:
                resp = fetcher.get(path)
                break
            except ChallengeError:
                stats.challenges += 1
                challenge_retries += 1
                if challenge_retries > 2:
                    stats.errors += 1
                    print(f"[{site.id}:{pid}] Cloudflare 验证反复失败，跳过", flush=True)
                    break
                print(f"[{site.id}:{pid}] 触发 Cloudflare 验证，重新取 cookie…", flush=True)
                credentials = get_credentials(
                    site.base_url, cookie_cache, max_age=0, force=True
                )
                fetcher.update_credentials(credentials)
            except Exception as exc:  # noqa: BLE001
                stats.errors += 1
                print(f"[{site.id}:{pid}] 请求失败: {exc}", flush=True)
                time.sleep(8)
                break

        if resp is None:
            time.sleep(random.uniform(delay_min, delay_max))
            continue

        # 请求成功（无论有没有商品）都算"这一轮看过"，merge 时才敢改状态
        result.visited.add(key)
        result.next_pid = pid + 1

        product = parse_product(
            resp.text,
            pid,
            site.base_url.rstrip("/") + site.link_path.format(pid=pid),
            provider=site.id,
            provider_name=site.name,
        )
        if product:
            product["status"] = "active"
            product["last_seen"] = utc_now()
            result.found[key] = product
            result.missing.discard(key)
            price = product.get("price_year")
            price_text = f"${price:,.2f}" if price is not None else "—"
            print(
                f"[{site.id}:{pid}] ✓ {product['name']}  "
                f"{product['cpu']} / {product['ram']} / {product['disk']} / "
                f"{product['traffic']} / {price_text}/yr",
                flush=True,
            )
        elif is_out_of_stock(resp.text):
            result.out_of_stock.add(key)
            result.missing.discard(key)
            print(f"[{site.id}:{pid}] 售罄", flush=True)
        else:
            result.missing.add(key)
            print(f"[{site.id}:{pid}] 无产品", flush=True)

        time.sleep(random.uniform(delay_min, delay_max))

    if result.complete:
        result.next_pid = min_pid

    stats.active = len(result.found)
    stats.out_of_stock = len(result.out_of_stock)
    stats.missing = len(result.missing)
    stats.incomplete = not result.complete
    stats.finished_at = utc_now()

    if on_checkpoint:
        _checkpoint(on_checkpoint, result, site, stats)
    return result


def _checkpoint(
    on_checkpoint: Callable[[CrawlResult], None],
    result: CrawlResult,
    site: Site,
    stats: CrawlStats,
) -> None:
    """中途落盘：写到一半被打断也不会白采。失败了不影响主流程。"""
    try:
        on_checkpoint(result)
    except Exception as exc:  # noqa: BLE001
        print(f"[main] {site.id}：检查点写入失败: {exc}", flush=True)
    else:
        print(
            f"[main] {site.id}：已落盘（请求 {stats.scanned}，"
            f"在售 {len(result.found)}，售罄 {len(result.out_of_stock)}）",
            flush=True,
        )


def build_progress(result: CrawlResult) -> dict[str, Any]:
    """生成 progress 记录。采完了就把游标指回 min_pid，下次重新全量复查。"""
    return {
        "next_pid": result.min_pid if result.complete else result.next_pid,
        "complete": result.complete,
        "min_pid": result.min_pid,
        "max_pid": result.max_pid,
        "updated_at": utc_now(),
    }


def merge_store(
    previous: dict[str, Any],
    result: CrawlResult,
    site: Site,
) -> dict[str, Any]:
    """把本次结果并入历史库：没扫到的旧产品保留数据，只更新状态。

    只有 result.visited 里的 pid（这一轮真请求过的）才允许改状态，
    这样采到一半中断/续采时，没轮到的商品不会被误标成 stale。
    """
    products: dict[str, Any] = dict(previous.get("products", {}))
    now = utc_now()

    for key, product in result.found.items():
        old = products.get(key, {})
        product.setdefault("first_seen", old.get("first_seen", now))
        products[key] = product

    for key, product in products.items():
        if key in result.found or key not in result.visited:
            continue
        product["status"] = (
            "out_of_stock" if key in result.out_of_stock else "stale"
        )

    return {
        "site": site.id,
        "name": site.name,
        "base_url": site.base_url,
        "products": products,
        "missing": sorted(int(pid) for pid in result.missing),
        "progress": build_progress(result),
    }
