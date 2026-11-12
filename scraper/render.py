"""把抓取结果渲染成 Markdown 表格和 GitHub Pages 静态页。"""

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


def render_markdown(products: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines = [
        f"# {meta.get('title', 'Budget VPS')}",
        "",
        f"> 数据源：{meta.get('source', '')} ｜ 更新：{_display_time(meta.get('updated_at', ''))} ｜ "
        f"共 {len(products)} 个在售套餐",
        "",
        "| Name | CPU | RAM | SSD | Traffic | Price (per year) |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for product in products:
        name = str(product["name"]).replace("|", "\\|")
        lines.append(
            "| [{name}]({url}) | {cpu} | {ram} | {disk} | {traffic} | {price} |".format(
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
        "价格说明：优先取 WHMCS 的年付价；只有月付时按 ×12 估算，页面上以 `*` 标注。",
        "",
        "由 `scraper/` 自动生成，请勿手工编辑。",
        "",
    ]
    return "\n".join(lines)


def render_html(products: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    rows = []
    for index, product in enumerate(products, start=1):
        name = html_lib.escape(str(product["name"]))
        url = html_lib.escape(product.get("url", ""), quote=True)
        price = product.get("price_year")
        marker = " *" if product.get("price_estimated") else ""
        rows.append(
            """
      <tr>
        <td class="num">{index}</td>
        <td class="name"><a href="{url}" target="_blank" rel="noopener">{name}</a></td>
        <td>{cpu}</td>
        <td>{ram}</td>
        <td>{disk}</td>
        <td>{traffic}</td>
        <td class="price" data-sort="{price_raw}">{price}{marker}</td>
        <td class="num pid hide-sm">{pid}</td>
      </tr>""".format(
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
        )

    template = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #0b0f17;
    --panel: #121826;
    --panel-2: #0f1521;
    --line: #1f2a3d;
    --text: #e6edf7;
    --muted: #8b9bb4;
    --accent: #4ade80;
    --accent-dim: #16a34a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: radial-gradient(1200px 600px at 20% -10%, #16233a 0%, var(--bg) 55%);
    color: var(--text); font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI",
    "PingFang SC", "Microsoft YaHei", sans-serif; min-height: 100vh;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 40px 20px 64px; }
  header h1 { margin: 0 0 8px; font-size: 30px; letter-spacing: .2px; }
  header p { margin: 0; color: var(--muted); }
  .stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 22px 0 18px; }
  .chip {
    background: var(--panel); border: 1px solid var(--line); border-radius: 999px;
    padding: 6px 13px; color: var(--muted); font-size: 13px;
  }
  .chip b { color: var(--text); font-weight: 600; }
  .bar { display: flex; gap: 10px; align-items: center; margin: 0 0 14px; flex-wrap: wrap; }
  input[type=search] {
    flex: 1 1 240px; background: var(--panel); color: var(--text); border: 1px solid var(--line);
    border-radius: 10px; padding: 10px 13px; font-size: 14px; outline: none;
  }
  input[type=search]:focus { border-color: var(--accent-dim); }
  .hint { color: var(--muted); font-size: 12.5px; }
  .tablewrap {
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px; overflow: auto;
  }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th {
    position: sticky; top: 0; background: var(--panel-2); font-size: 12.5px;
    text-transform: uppercase; letter-spacing: .06em; color: var(--muted); cursor: pointer;
    user-select: none;
  }
  th:hover { color: var(--text); }
  tbody tr:hover { background: #162032; }
  tbody tr:last-child td { border-bottom: 0; }
  td.name a { color: var(--text); text-decoration: none; font-weight: 550; }
  td.name a:hover { color: var(--accent); }
  td.price { color: var(--accent); font-weight: 600; }
  td.num { color: var(--muted); width: 1%; }
  td.pid { font-size: 12px; }
  .empty { padding: 28px; text-align: center; color: var(--muted); }
  footer { margin-top: 18px; color: var(--muted); font-size: 13px; }
  footer code { background: var(--panel); padding: 2px 6px; border-radius: 6px; }
  a { color: var(--accent); }
  @media (max-width: 720px) { .hide-sm { display: none; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>__TITLE__</h1>
    <p>__SUBTITLE__</p>
    <div class="stats">
      <span class="chip">在售套餐 <b>__COUNT__</b></span>
      <span class="chip">售罄 <b>__OOS__</b></span>
      <span class="chip">扫描 pid <b>__SCANNED__</b></span>
      <span class="chip">更新 <b>__UPDATED__</b></span>
    </div>
  </header>

  <div class="bar">
    <input id="q" type="search" placeholder="搜索名称 / CPU / 内存 / 价格…">
    <span class="hint">点表头排序 · 价格优先取年付价，`*` 表示按月付 ×12 估算</span>
  </div>

  <div class="tablewrap">
    <table id="t">
      <thead>
        <tr>
          <th>#</th>
          <th>Name</th>
          <th>CPU</th>
          <th>RAM</th>
          <th>SSD</th>
          <th>Traffic</th>
          <th>Price / yr</th>
          <th class="hide-sm">PID</th>
        </tr>
      </thead>
      <tbody>
__ROWS__
      </tbody>
    </table>
    <div class="empty" id="empty" hidden>没有匹配的结果</div>
  </div>

  <footer>
    数据来自 <a href="__SOURCE__" target="_blank" rel="noopener">__SOURCE_HOST__</a> 的 WHMCS 购物车，
    由 GitHub Actions 定时抓取。原始数据：<a href="data.json">data.json</a> ·
    Markdown：<a href="index.md">index.md</a>
  </footer>
</div>
<script>
(function () {
  var table = document.getElementById('t');
  var tbody = table.tBodies[0];
  var q = document.getElementById('q');
  var empty = document.getElementById('empty');

  q.addEventListener('input', function () {
    var term = q.value.trim().toLowerCase();
    var shown = 0;
    Array.prototype.forEach.call(tbody.rows, function (row) {
      var hit = !term || row.innerText.toLowerCase().indexOf(term) !== -1;
      row.hidden = !hit;
      if (hit) shown++;
    });
    empty.hidden = shown !== 0;
  });

  Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, idx) {
    if (idx === 0) return;
    th.addEventListener('click', function () {
      var rows = Array.prototype.slice.call(tbody.rows);
      var numeric = idx === 6;
      var dir = th.dataset.dir === 'asc' ? -1 : 1;
      th.dataset.dir = dir === 1 ? 'asc' : 'desc';
      rows.sort(function (a, b) {
        var x = a.cells[idx].innerText.trim();
        var y = b.cells[idx].innerText.trim();
        if (numeric) {
          x = parseFloat(a.cells[idx].dataset.sort || x.replace(/[^0-9.]/g, '')) || 0;
          y = parseFloat(b.cells[idx].dataset.sort || y.replace(/[^0-9.]/g, '')) || 0;
          return (x - y) * dir;
        }
        return x.localeCompare(y, 'en') * dir;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
})();
</script>
</body>
</html>
"""

    source = meta.get("source", "")
    from urllib.parse import urlparse

    host = urlparse(source).netloc or source
    return (
        template.replace("__TITLE__", html_lib.escape(meta.get("title", "Budget VPS")))
        .replace("__SUBTITLE__", html_lib.escape(meta.get("subtitle", "")))
        .replace("__COUNT__", str(len(products)))
        .replace("__OOS__", str(meta.get("out_of_stock", 0)))
        .replace("__SCANNED__", str(meta.get("scanned", 0)))
        .replace("__UPDATED__", html_lib.escape(_display_time(meta.get("updated_at", ""))))
        .replace("__ROWS__", "".join(rows))
        .replace("__SOURCE__", html_lib.escape(source, quote=True))
        .replace("__SOURCE_HOST__", html_lib.escape(host))
    )


def write_outputs(
    store: dict[str, Any],
    docs_dir: Path,
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    products = active_products(store)
    docs_dir.mkdir(parents=True, exist_ok=True)

    meta = dict(meta)
    meta.setdefault(
        "updated_at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )

    (docs_dir / "index.md").write_text(
        render_markdown(products, meta), encoding="utf-8"
    )
    (docs_dir / "index.html").write_text(
        render_html(products, meta), encoding="utf-8"
    )
    (docs_dir / "data.json").write_text(
        json.dumps(
            {
                "generated_at": meta["updated_at"],
                "source": meta.get("source", ""),
                "stats": {
                    "active": len(products),
                    "out_of_stock": meta.get("out_of_stock", 0),
                    "scanned": meta.get("scanned", 0),
                },
                "products": sorted(
                    store.get("products", {}).values(),
                    key=lambda p: int(p.get("pid", 0)),
                ),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return products
