"""命令行入口：抓取 + 生成页面。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .cf import get_credentials
from .crawler import crawl, load_store, merge_store, utc_now
from .render import write_outputs

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = os.getenv("BASE_URL", "https://billing.dedirock.com")
DATA_PATH = ROOT / "data" / "products.json"
COOKIE_PATH = ROOT / "data" / ".cookies.json"
DOCS_DIR = ROOT / "docs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="扫描 WHMCS 的 pid，抓 VPS 配置和年价，生成 Markdown / GitHub Pages"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="WHMCS 站点根地址")
    parser.add_argument("--min-pid", type=int, default=int(os.getenv("MIN_PID", "1")))
    parser.add_argument("--max-pid", type=int, default=int(os.getenv("MAX_PID", "400")))
    parser.add_argument(
        "--delay-min", type=float, default=float(os.getenv("DELAY_MIN", "2.5"))
    )
    parser.add_argument(
        "--delay-max", type=float, default=float(os.getenv("DELAY_MAX", "4.0"))
    )
    parser.add_argument(
        "--cf-cache-minutes",
        type=float,
        default=float(os.getenv("CF_CACHE_MINUTES", "20")),
        help="cf_clearance 复用时长（分钟）",
    )
    parser.add_argument(
        "--no-crawl", action="store_true", help="只根据已有 data/products.json 重新生成页面"
    )
    parser.add_argument(
        "--reparse",
        action="store_true",
        help="不联网，用已保存的 specs_raw 重新解析字段（改了正则后很有用）",
    )
    parser.add_argument(
        "--force-solve", action="store_true", help="忽略 cookie 缓存，强制重新过 Cloudflare"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.time()

    previous = load_store(DATA_PATH)
    previous_stats = previous.get("stats") or {}

    if args.reparse:
        from .parse import parse_cpu, parse_disk, parse_ram, parse_traffic

        for product in previous.get("products", {}).values():
            raw = product.get("specs_raw") or []
            text = " | ".join(raw)
            product["cpu"], product["cpu_model"] = parse_cpu(text)
            product["ram"] = parse_ram(text)
            product["disk"] = parse_disk(text)
            product["traffic"] = parse_traffic(text)
        print("[main] --reparse：已用 specs_raw 重新解析", flush=True)

    if args.no_crawl:
        store = previous
        stats = None
        print("[main] --no-crawl：跳过抓取，直接渲染", flush=True)
    else:
        credentials = get_credentials(
            args.base_url,
            COOKIE_PATH,
            max_age=args.cf_cache_minutes * 60,
            force=args.force_solve,
        )
        result = crawl(
            base_url=args.base_url,
            min_pid=args.min_pid,
            max_pid=args.max_pid,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            credentials=credentials,
            cookie_cache=COOKIE_PATH,
        )
        stats = result.stats
        store = merge_store(previous, result)

    data_updated = (
        stats.finished_at if stats else previous_stats.get("finished_at")
    ) or utc_now()

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(
        json.dumps(
            {
                "source": args.base_url,
                "updated_at": data_updated,
                "stats": stats.__dict__ if stats else previous_stats,
                "products": store.get("products", {}),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    meta = {
        "title": "Budget VPS 价格表",
        "subtitle": f"WHMCS 购物车全量扫描 · 数据源 {args.base_url}",
        "source": args.base_url,
        "out_of_stock": (
            stats.out_of_stock if stats else previous_stats.get("out_of_stock", 0)
        ),
        "scanned": stats.scanned if stats else previous_stats.get("scanned", 0),
        "updated_at": data_updated,
    }
    products = write_outputs(store, DOCS_DIR, meta)

    elapsed = time.time() - started
    print(
        f"[main] 完成：{len(products)} 个在售套餐，"
        f"{meta['out_of_stock']} 个售罄，用时 {elapsed / 60:.1f} 分钟",
        flush=True,
    )
    print(f"[main] 输出：{DOCS_DIR / 'index.html'}  {DOCS_DIR / 'index.md'}", flush=True)

    if stats and stats.active == 0:
        print("[main] 警告：本次没有抓到任何产品，请检查 Cloudflare / 站点结构", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
