"""把各站点数据渲染成 Markdown 表格和静态 HTML 页面。

HTML 是模板驱动的：`templates/index.html` 里的 `{{...}}` 占位符在构建时替换，
构建产物（`_site/`）不入库，GitHub Actions 每次现生成。
"""

from __future__ import annotations

import html as html_lib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _price(value: Any) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def _display_time(value: str) -> str:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return moment.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(value)


def _sort_key(product: dict[str, Any]) -> tuple:
    price = product.get("price_year")
    return (price is None, price if price is not None else 0, product.get("name", ""))


def active_products(store: dict[str, Any]) -> list[dict[str, Any]]:
    items = [
        p
        for p in store.get("products", {}).values()
        if p.get("status") == "active" and p.get("price_year") is not None
    ]
    return sorted(items, key=_sort_key)


def unavailable_products(store: dict[str, Any]) -> list[dict[str, Any]]:
    """有历史数据、但这一轮不可用（售罄 / 没抓到，可能已下架）的商品。

    这类商品不再从列表里删掉，只是标记为不可用，渲染时划删除线。
    """
    items = [
        p
        for p in store.get("products", {}).values()
        if p.get("status") != "active"
    ]
    return sorted(items, key=_sort_key)


def _unavailable_label(product: dict[str, Any]) -> str:
    return "本轮售罄" if product.get("status") == "out_of_stock" else "本轮未抓到，可能已下架"


def provider_names(stores: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for store in stores:
        site = store.get("meta", {}).get("site", "")
        name = store.get("meta", {}).get("name", site)
        names[site] = name
    return names


def provider_counts(stores: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for store in stores:
        for product in store.get("products", {}).values():
            if product.get("status") == "active" and product.get("price_year") is not None:
                key = product.get("provider") or store.get("meta", {}).get("site", "?")
                counts[key] = counts.get(key, 0) + 1
    return counts


def render_markdown(products: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines = [
        f"# {meta.get('title', 'Budget VPS')}",
        "",
        f"> 数据源：{meta.get('sources_text', '')} ｜ 更新：{_display_time(meta.get('updated_at', ''))} ｜ "
        f"共 {meta.get('count', len(products))} 个在售套餐"
        f"，{meta.get('unavailable', 0)} 个本轮不可用（已删除线标注）",
        "",
        "| Provider | Name | CPU | RAM | Storage | Traffic | Price (per year) |",
        "| --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for product in products:
        name = str(product["name"]).replace("|", "\\|")
        if product.get("status") != "active":
            name = f"~~{name}~~"
        provider = str(product.get("provider_name") or product.get("provider") or "—")
        provider = provider.replace("|", "\\|")
        lines.append(
            "| {provider} | [{name}]({url}) | {cpu} | {ram} | {disk} | {traffic} | {price} |".format(
                provider=provider,
                name=name,
                url=product.get("url", ""),
                cpu=product.get("cpu", "—"),
                ram=product.get("ram", "—"),
                disk=product.get("disk", "—"),
                traffic=product.get("traffic", "—"),
                price=_price(product.get("price_year")),
            )
        )
    lines += [
        "",
        "价格说明：优先取 WHMCS 的年付价；只有月付时按 ×12 估算，页面上以 `*` 标注。"
        "Storage 统一为 GB，Traffic 统一为 TB。",
        "",
        "由 `scraper/` 自动生成，请勿手工编辑。",
        "",
    ]
    return "\n".join(lines)


def _row(index: int, product: dict[str, Any]) -> str:
    name = html_lib.escape(str(product["name"]))
    url = html_lib.escape(product.get("url", ""), quote=True)
    price = product.get("price_year")
    marker = " *" if product.get("price_estimated") else ""
    provider = html_lib.escape(str(product.get("provider") or ""))
    provider_name = html_lib.escape(
        str(product.get("provider_name") or product.get("provider") or "—")
    )
    unavailable = product.get("status") != "active"
    row_cls = ' class="unavail"' if unavailable else ""
    row_title = (
        ' title="{0}"'.format(html_lib.escape(_unavailable_label(product), quote=True))
        if unavailable
        else ""
    )
    return """<tr data-provider="{provider}"{row_cls}{row_title}>
        <td class="num">{index}</td>
        <td class="provider"><span class="badge {provider}">{provider_name}</span></td>
        <td class="name"><a href="{url}" target="_blank" rel="noopener">{name}</a></td>
        <td>{cpu}</td>
        <td>{ram}</td>
        <td>{disk}</td>
        <td>{traffic}</td>
        <td class="price" data-sort="{price_raw}">{price}{marker}</td>
        <td class="num pid hide-sm">{pid}</td>
      </tr>""".format(
        provider=provider,
        provider_name=provider_name,
        row_cls=row_cls,
        row_title=row_title,
        index=index,
        url=url,
        name=name,
        cpu=html_lib.escape(product.get("cpu", "—")),
        ram=html_lib.escape(product.get("ram", "—")),
        disk=html_lib.escape(product.get("disk", "—")),
        traffic=html_lib.escape(product.get("traffic", "—")),
        price=_price(price),
        price_raw=price if price is not None else 0,
        marker=marker,
        pid=product.get("pid", ""),
    )


def render_html(products: list[dict[str, Any]], meta: dict[str, Any], template: str) -> str:
    rows = "".join(_row(index, product) for index, product in enumerate(products, start=1))

    replacements = {
        "title": html_lib.escape(meta.get("title", "Budget VPS")),
        "subtitle": html_lib.escape(meta.get("subtitle", "")),
        "count": str(meta.get("count", len(products))),
        "unavailable": str(meta.get("unavailable", 0)),
        "out_of_stock": str(meta.get("out_of_stock", 0)),
        "scanned": str(meta.get("scanned", 0)),
        "skipped": str(meta.get("skipped", 0)),
        "updated": html_lib.escape(_display_time(meta.get("updated_at", ""))),
        "provider_chips": meta.get("provider_chips", ""),
        "provider_options": meta.get("provider_options", ""),
        "rows": rows,
        "sources": meta.get("sources", ""),
    }
    html = template
    for key, value in replacements.items():
        html = html.replace("{{" + key + "}}", value)
    return html


def build_site(
    stores: list[dict[str, Any]],
    out_dir: Path,
    template_path: Path,
) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for store in stores:
        active.extend(active_products(store))
        unavailable.extend(unavailable_products(store))
    # 在售排前面，本轮不可用的（删除线）排后面
    active.sort(key=_sort_key)
    unavailable.sort(key=_sort_key)
    products = active + unavailable

    names = provider_names(stores)
    counts = provider_counts(stores)

    chips = "".join(
        f'\n      <span class="chip">{html_lib.escape(names.get(site, site))} <b>{count}</b></span>'
        for site, count in sorted(counts.items())
    )
    options = "".join(
        f'\n        <option value="{html_lib.escape(site)}">{html_lib.escape(names.get(site, site))}</option>'
        for site in sorted(counts)
    )
    sources = " · ".join(
        f'<a href="{html_lib.escape(store["meta"].get("base_url", ""), quote=True)}" '
        f'target="_blank" rel="noopener">{html_lib.escape(names.get(store["meta"].get("site", ""), ""))}</a>'
        for store in stores
    )

    updated_at = max(
        (store.get("meta", {}).get("updated_at") or "" for store in stores), default=""
    )
    meta = {
        "title": "Budget VPS 价格表",
        "count": len(active),
        "unavailable": len(unavailable),
        "subtitle": "WHMCS 购物车全量扫描 · " + " / ".join(
            f"{names.get(site, site)} {count}" for site, count in sorted(counts.items())
        ),
        "sources_text": " · ".join(
            f'{names.get(store["meta"].get("site", ""), "")} {store["meta"].get("base_url", "")}'
            for store in stores
        ),
        "sources": sources,
        "out_of_stock": sum(
            store.get("meta", {}).get("stats", {}).get("out_of_stock", 0) for store in stores
        ),
        "scanned": sum(
            store.get("meta", {}).get("stats", {}).get("scanned", 0) for store in stores
        ),
        "skipped": sum(
            store.get("meta", {}).get("stats", {}).get("skipped", 0) for store in stores
        ),
        "updated_at": updated_at,
        "provider_chips": chips,
        "provider_options": options,
    }

    template = template_path.read_text(encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.md").write_text(render_markdown(products, meta), encoding="utf-8")
    (out_dir / "index.html").write_text(render_html(products, meta, template), encoding="utf-8")
    (out_dir / "data.json").write_text(
        json.dumps(
            {
                "generated_at": _display_time(updated_at),
                "sites": [
                    {
                        "site": store.get("meta", {}).get("site", ""),
                        "name": names.get(store.get("meta", {}).get("site", ""), ""),
                        "base_url": store.get("meta", {}).get("base_url", ""),
                        "updated_at": store.get("meta", {}).get("updated_at", ""),
                        "stats": store.get("meta", {}).get("stats", {}),
                    }
                    for store in stores
                ],
                "products": sorted(
                    (
                        product
                        for store in stores
                        for product in store.get("products", {}).values()
                    ),
                    key=lambda p: (
                        p.get("provider", ""),
                        int(p.get("pid", 0)),
                    ),
                ),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return products
