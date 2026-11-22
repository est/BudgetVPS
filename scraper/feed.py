"""WHMCS 公开 feed 客户端。

`feeds/productsinfo.php` 不需要登录，也不走 Cloudflare 验证，一次取一个字段：

    /feeds/productsinfo.php?pid=968&get=name
    /feeds/productsinfo.php?pid=968&get=description
    /feeds/productsinfo.php?pid=968&get=price&billingcycle=annually

返回的是 JS：`document.write('...');`，需要先解掉 addslashes 的转义。

注意：feed 不返回库存状态，所以 DediRock 的 active/out_of_stock 沿用上一次
抓取结果；feed 失败、或者 pid 不在历史库里时，回退到 cart.php 的 HTML 解析。
后者是为了避开 feed 里那些已下架/隐藏商品（Retired Product 等）。
"""

from __future__ import annotations

import re
from typing import Any

from .parse import build_product, clean_text

FEED_PATH = "/feeds/productsinfo.php?pid={pid}&get={field}"

_WIDGET_RE = re.compile(r"document\.write\('(.*)'\);\s*$", re.S)
_PRICE_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


class FeedNotFound(RuntimeError):
    """feed 明确说这个 pid 不存在。"""


class FeedError(RuntimeError):
    """feed 取不到 / 解析不了，需要回退 cart。"""


class FeedNoPrice(FeedError):
    """feed 能取到商品，但没有 annually/monthly 价格，回退 cart 拿其它周期。"""


class FeedNeedsCart(FeedError):
    """pid 不在历史库里，feed 只能确认存在，交给 cart 判断是否真的可订购。"""


def parse_widget(text: str) -> str | None:
    """从 `document.write('...');` 里取出字符串，解掉 addslashes。"""
    match = _WIDGET_RE.search(text)
    if not match:
        return None
    return _unescape(match.group(1))


def _unescape(value: str) -> str:
    """还原 PHP addslashes：\\' \\" \\\\ \\0。"""
    out: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            nxt = value[index + 1]
            if nxt in "'\"\\":
                out.append(nxt)
                index += 2
                continue
            if nxt == "0":
                out.append("\0")
                index += 2
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _field(fetcher: Any, pid: int, field: str, **params: str) -> str:
    path = FEED_PATH.format(pid=pid, field=field)
    if params:
        path += "&" + "&".join(f"{key}={value}" for key, value in params.items())

    response = fetcher.get(path)
    if response.status_code != 200:
        raise FeedError(f"{field}: HTTP {response.status_code}")

    value = parse_widget(response.text)
    if value is None:
        raise FeedError(f"{field}: 不是 document.write 格式")
    return value


def _price(fetcher: Any, pid: int, cycle: str) -> float | None:
    value = _field(fetcher, pid, "price", billingcycle=cycle)
    match = _PRICE_RE.search(value)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def fetch_product(
    fetcher: Any,
    site: Any,
    pid: int,
    previous: dict[str, Any] | None = None,
    known: bool = True,
) -> dict[str, Any]:
    """按 feed 组装产品；pid 不存在抛 FeedNotFound，其它失败抛 FeedError。

    DediRock 目前只有 annually / monthly 两种周期；annual 不可用时 feed 返回
    $-1.00，再试 monthly。两种都没有就回退 cart（cart 还能拿到 quarterly 等）。

    `known=False` 时只查 name：feed 里有很多已下架/隐藏商品（Retired Product、
    Account Ownership Transfer 等），不能让它们混进列表，必须回退 cart 确认。
    """
    name = _field(fetcher, pid, "name")
    if name == "Product ID Not Found":
        raise FeedNotFound(str(pid))
    if not name:
        raise FeedError("name 为空")
    if not known:
        raise FeedNeedsCart(name)

    description = _field(fetcher, pid, "description")
    if description == "Product ID Not Found":
        raise FeedNotFound(str(pid))

    cycles: list[dict[str, Any]] = []
    annual = _price(fetcher, pid, "annually")
    if annual is not None and annual >= 0:
        cycles.append({"cycle": "annually", "price": annual, "label": ""})
    else:
        monthly = _price(fetcher, pid, "monthly")
        if monthly is not None and monthly >= 0:
            cycles.append({"cycle": "monthly", "price": monthly, "label": ""})
        else:
            raise FeedNoPrice("annually/monthly 都没有可用价格")

    lines = [clean_text(part) for part in re.split(r"<br\s*/?>", description)]
    lines = [line for line in lines if line]

    product = build_product(
        pid,
        name,
        lines,
        cycles,
        site.base_url.rstrip("/") + site.link_path.format(pid=pid),
        provider=site.id,
        provider_name=site.name,
    )

    # feed 没有库存字段：已知售罄的保持售罄，其余按在售处理。
    previous = previous or {}
    product["status"] = (
        "out_of_stock" if previous.get("status") == "out_of_stock" else "active"
    )
    return product
