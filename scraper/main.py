"""命令行入口：按站点抓取 + 生成静态页面。"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .cf import DEFAULT_UA, get_credentials
from .crawler import build_progress, crawl, merge_store, utc_now
from .render import build_site
from .sites import Site, get_sites
from .store import read_site, write_site

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "_site"
TEMPLATE_PATH = ROOT / "templates" / "index.html"

# cf_clearance 要起浏览器，多个站点同时过验证容易互相踩，串行化
_CRED_LOCK = threading.Lock()


def default_credentials() -> dict[str, Any]:
    return {"user_agent": DEFAULT_UA, "cookies": {}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="扫描 WHMCS 站点的 pid，抓 VPS 配置和年价，生成 Markdown / 静态页"
    )
    parser.add_argument(
        "--site", default=os.getenv("SITE", "all"),
        help="站点 id，逗号分隔（可选：dedirock, racknerd）；默认全部",
    )
    parser.add_argument("--min-pid", type=int, default=int(os.getenv("MIN_PID", "1")))
    parser.add_argument(
        "--max-pid", type=int, default=0,
        help="结束 pid，0 表示用 MAX_PID / <SITE>_MAX_PID / 站点配置",
    )
    parser.add_argument(
        "--delay-min", type=float,
        default=float(os.getenv("DELAY_MIN", "0")) or None,
        help="最小请求间隔（秒），默认用站点配置",
    )
    parser.add_argument(
        "--delay-max", type=float,
        default=float(os.getenv("DELAY_MAX", "0")) or None,
        help="最大请求间隔（秒），默认用站点配置",
    )
    parser.add_argument(
        "--cf-cache-minutes",
        type=float,
        default=float(os.getenv("CF_CACHE_MINUTES", "20")),
        help="cf_clearance 复用时长（分钟）",
    )
    parser.add_argument(
        "--budget-minutes",
        type=float,
        default=float(os.getenv("CRAWL_BUDGET_MINUTES", "50")),
        help="整轮抓取的时间预算（分钟），到点就停、已采的照常保存，0 表示不限时",
    )
    parser.add_argument(
        "--no-crawl", action="store_true", help="只根据已有 data/*.ndjson 重新生成页面"
    )
    parser.add_argument(
        "--reparse",
        action="store_true",
        help="不联网，用已保存的 specs_raw 重新解析字段（改了正则后很有用）",
    )
    parser.add_argument("--force-solve", action="store_true", help="忽略 cookie 缓存，强制重新过 Cloudflare")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="静态页输出目录")
    parser.add_argument("--template", default=str(TEMPLATE_PATH), help="HTML 模板")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="数据目录")
    return parser


def reparse_site(store: dict[str, Any]) -> None:
    from .parse import parse_cpu, parse_disk, parse_ram, parse_traffic

    for product in store["products"].values():
        # 规格为空的商品退回用标题解析（和在线解析保持一致）
        text = " | ".join(product.get("specs_raw") or []) or str(product.get("name") or "")
        product["cpu"], product["cpu_model"] = parse_cpu(text)
        product["ram"] = parse_ram(text)
        product["disk"] = parse_disk(text)
        product["traffic"] = parse_traffic(text)


def _resolve(value: float | None, fallback: float) -> float:
    return value if value is not None else fallback


def resolve_max_pid(site: Site, cli_value: int) -> tuple[int, str]:
    """结束 pid 的来源，返回 (值, 来源说明)。

    优先级：`--max-pid` > `MAX_PID` > `<SITE>_MAX_PID`（按站点）> 站点配置。
    按站点的环境变量是为了在 GitHub Actions 里单独调某个站的扫描上限，
    不用因为 racknerd 涨了就把 dedirock 也一起撑大。
    """
    if cli_value:
        return cli_value, "--max-pid"

    for key in ("MAX_PID", f"{site.id.upper()}_MAX_PID"):
        raw = os.getenv(key, "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            print(f"[main] 忽略无效的 {key}={raw!r}", flush=True)
            continue
        if value > 0:
            return value, key

    return site.max_pid, "sites.py"


def previous_store(site: Site, store: dict[str, Any]) -> dict[str, Any]:
    """抓取失败时的兜底视图：直接用磁盘上的老数据。

    这样站点不会因为一次抓取失败就从页面上消失，旧商品（含售罄 / stale）
    的状态也原样保留。
    """
    meta = dict(store.get("meta") or {})
    meta.update({"site": site.id, "name": site.name, "base_url": site.base_url})
    if not meta.get("updated_at"):
        meta["updated_at"] = utc_now()
    return {
        "meta": meta,
        "missing": list(store.get("missing") or []),
        "products": dict(store.get("products") or {}),
    }


def process_site(
    site: Site,
    args: argparse.Namespace,
    data_dir: Path,
    deadline: float | None = None,
) -> dict[str, Any]:
    path = data_dir / f"{site.id}.ndjson"
    store = read_site(path)

    if args.reparse:
        reparse_site(store)
        print(f"[main] --reparse：{site.id} 已用 specs_raw 重新解析", flush=True)

    if args.no_crawl:
        stats = dict(store["meta"].get("stats") or {})
        stats.setdefault("active", len(store["products"]))
        updated_at = store["meta"].get("updated_at") or utc_now()
        if args.reparse:
            write_site(path, site, stats, store["missing"], store["products"],
                       updated_at, store.get("progress"))
        print(
            f"[main] --no-crawl：{site.id} 跳过抓取，{len(store['products'])} 个历史产品",
            flush=True,
        )
        meta = dict(store["meta"])
        meta.update(
            {
                "site": site.id,
                "name": site.name,
                "base_url": site.base_url,
                "updated_at": updated_at,
                "stats": stats,
            }
        )
        return {
            "meta": meta,
            "missing": store["missing"],
            "products": store["products"],
        }

    credentials = default_credentials()
    cookie_cache = data_dir / f".cookies-{site.id}.json"

    max_pid, max_pid_src = resolve_max_pid(site, args.max_pid)
    delay_min = _resolve(args.delay_min, site.delay_min)
    delay_max = _resolve(args.delay_max, site.delay_max)

    print(
        f"[main] {site.name}：扫描 pid {args.min_pid}..{max_pid}（上限来自 {max_pid_src}），"
        f"间隔 {delay_min:.1f}-{delay_max:.1f}s",
        flush=True,
    )

    def checkpoint(result) -> None:
        """中途落盘：被打断时磁盘上已经是最新进度。

        只做加法（mark_stale=False），不把任何旧商品标成 stale；一个成功请求都
        没拿到时干脆不写，免得把上一轮的数据改坏。
        """
        if result.stats.ok == 0:
            return
        partial = merge_store(store, result, site, mark_stale=False)
        write_site(
            path, site, result.stats.__dict__,
            partial["missing"], partial["products"], utc_now(), partial["progress"],
        )

    try:
        # feed 主路径不需要 Cloudflare；只有回退 cart 撞到验证时，crawl() 里才会去取 cookie
        if site.cloudflare and not site.feed:
            with _CRED_LOCK:
                credentials = get_credentials(
                    site.base_url,
                    cookie_cache,
                    max_age=args.cf_cache_minutes * 60,
                    force=args.force_solve,
                )

        result = crawl(
            site=site,
            min_pid=args.min_pid,
            max_pid=max_pid,
            delay_min=delay_min,
            delay_max=delay_max,
            credentials=credentials,
            cookie_cache=cookie_cache,
            previous=store,
            deadline=deadline,
            on_checkpoint=checkpoint,
        )
    except Exception as exc:  # noqa: BLE001
        # 过 Cloudflare 失败 / 站点挂掉等等，一律不动已有的数据
        print(
            f"[main] {site.name}：本轮抓取失败（{exc}），保留上一轮数据，站点仍在页面上",
            flush=True,
        )
        return previous_store(site, store)

    if result.stats.failed:
        print(
            f"[main] {site.name}：本轮没有抓到任何有效数据"
            f"（请求 {result.stats.scanned}，成功响应 {result.stats.ok}），"
            f"保留上一轮数据不动",
            flush=True,
        )
        return previous_store(site, store)

    merged = merge_store(store, result, site)
    stats = result.stats.__dict__
    updated_at = stats["finished_at"] or utc_now()
    write_site(
        path, site, stats, merged["missing"], merged["products"],
        updated_at, merged["progress"],
    )

    print(
        f"[main] {site.name}：本次请求 {stats['scanned']}，跳过 {stats['skipped']}，"
        f"在售 {stats['active']}，售罄 {stats['out_of_stock']}，"
        f"无产品 {stats['missing']}，错误 {stats['errors']}"
        + ("，未采完（下轮继续）" if stats.get("incomplete") else ""),
        flush=True,
    )
    if result.stats.active == 0 and site.cloudflare:
        print(f"[main] 警告：{site.name} 本次没有抓到任何产品，请检查 Cloudflare / 站点结构",
              flush=True)
    meta = dict(store["meta"])
    meta.update(
        {
            "site": site.id,
            "name": site.name,
            "base_url": site.base_url,
            "updated_at": updated_at,
            "stats": stats,
        }
    )
    return {
        "meta": meta,
        "missing": merged["missing"],
        "products": merged["products"],
    }


def run_sites(
    sites: list[Site],
    args: argparse.Namespace,
    data_dir: Path,
    deadline: float | None,
) -> list[dict[str, Any]]:
    """不同供应商之间并发采集；每个站点的请求间隔照旧，互不影响。"""
    if len(sites) <= 1:
        return [
            process_site(site, args, data_dir, deadline)
            for site in sites
        ]

    done: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(sites)) as pool:
        futures = {
            pool.submit(process_site, site, args, data_dir, deadline): site
            for site in sites
        }
        for future in as_completed(futures):
            site = futures[future]
            try:
                done[site.id] = future.result()
            except Exception as exc:  # noqa: BLE001
                # 一个站点失败不影响别的站点；已落盘的检查点都还在
                print(f"[main] {site.id} 抓取异常（其它站点继续）: {exc}", flush=True)
                fallback = previous_store(site, read_site(data_dir / f"{site.id}.ndjson"))
                if fallback["products"]:
                    print(f"[main] {site.id}：改用磁盘上的上一轮数据渲染", flush=True)
                    done[site.id] = fallback
    return [done[site.id] for site in sites if site.id in done]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.time()

    # --reparse 的意义就是“不联网，只重新解析已有数据”
    if args.reparse:
        args.no_crawl = True

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    budget = args.budget_minutes
    deadline = time.monotonic() + budget * 60 if budget and budget > 0 else None
    if deadline:
        print(f"[main] 时间预算 {budget:.0f} 分钟，到点收工并保存已采数据", flush=True)

    sites = get_sites(args.site)
    stores: list[dict[str, Any]] = []
    for store in run_sites(sites, args, data_dir, deadline):
        if store["products"]:
            stores.append(store)
        else:
            print(f"[main] {store['meta'].get('site')} 没有数据，跳过", flush=True)

    if not stores:
        print("[main] 没有任何可用数据", flush=True)
        return 1

    out_dir = Path(args.out_dir)
    build_site(stores, out_dir, Path(args.template))

    active = sum(
        1 for s in stores for p in s["products"].values() if p.get("status") == "active"
    )
    listed = sum(len(s["products"]) for s in stores)
    oos = sum(s["meta"].get("stats", {}).get("out_of_stock", 0) for s in stores)
    scanned = sum(s["meta"].get("stats", {}).get("scanned", 0) for s in stores)
    skipped = sum(s["meta"].get("stats", {}).get("skipped", 0) for s in stores)
    unfinished = [
        s["meta"].get("stats", {})
        for s in stores
        if s["meta"].get("stats", {}).get("incomplete")
    ]
    print(
        f"[main] 完成：{active} 个在售套餐（列表共 {listed} 条，含划线的不可用），"
        f"{oos} 个售罄，本次请求 {scanned}，跳过 {skipped}，用时 {(time.time() - started) / 60:.1f} 分钟",
        flush=True,
    )
    if unfinished:
        names = "、".join(
            s["meta"].get("name", s["meta"].get("site", "?")) for s in stores
            if s["meta"].get("stats", {}).get("incomplete")
        )
        print(
            f"[main] 注意：{names} 本轮没采完（时间预算），数据已保存，下次自动接着采",
            flush=True,
        )
    print(f"[main] 输出：{out_dir / 'index.html'}  {out_dir / 'index.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
