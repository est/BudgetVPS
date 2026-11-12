"""站点配置。

所有站点都是 WHMCS，区别只在商品 URL 和是否挂 Cloudflare。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    base_url: str
    crawl_path: str
    link_path: str
    max_pid: int
    cloudflare: bool = True
    delay_min: float = 2.5
    delay_max: float = 4.0


SITES: dict[str, Site] = {
    "dedirock": Site(
        id="dedirock",
        name="DediRock",
        base_url="https://billing.dedirock.com",
        crawl_path="/aff.php?aff=1033&pid={pid}",
        link_path="/aff.php?aff=1033&pid={pid}",
        max_pid=400,
        cloudflare=True,
    ),
    "racknerd": Site(
        id="racknerd",
        name="RackNerd",
        base_url="https://my.racknerd.com",
        crawl_path="/aff.php?aff=1865&pid={pid}",
        link_path="/aff.php?aff=1865&pid={pid}",
        max_pid=280,
        cloudflare=False,
    ),
}


def get_sites(selector: str | None) -> list[Site]:
    if not selector or selector == "all":
        return list(SITES.values())
    wanted = [part.strip() for part in selector.split(",") if part.strip()]
    missing = [name for name in wanted if name not in SITES]
    if missing:
        raise SystemExit(f"未知站点: {', '.join(missing)}（可选: {', '.join(SITES)}）")
    return [SITES[name] for name in wanted]
