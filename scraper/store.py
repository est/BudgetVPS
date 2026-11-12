"""站点数据存取：每个站点一个 NDJSON 文件。

`data/<site>.ndjson` 每行一个 JSON 对象：

    {"type":"meta","site":"dedirock","name":"DediRock","base_url":"...","updated_at":"...","stats":{...}}
    {"type":"missing","pids":[2,3,4]}
    {"type":"product","pid":36,"name":"...","status":"active",...}

NDJSON 比单个大 JSON 更适合这里：改动集中在个别商品时 diff 一目了然，
追加 / 合并也只需要按行处理。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .sites import Site


def read_site(path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    missing: list[int] = []
    products: dict[str, dict[str, Any]] = {}

    if not path.exists():
        return {"meta": meta, "missing": missing, "products": products}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = record.get("type")
        if kind == "meta":
            meta = record
        elif kind == "missing":
            missing = [int(pid) for pid in record.get("pids", [])]
        elif kind == "product":
            products[str(record.get("pid"))] = record
    return {"meta": meta, "missing": missing, "products": products}


def write_site(
    path: Path,
    site: Site,
    stats: dict[str, Any] | None,
    missing: set[int] | list[int],
    products: dict[str, dict[str, Any]],
    updated_at: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "type": "meta",
        "site": site.id,
        "name": site.name,
        "base_url": site.base_url,
    }
    if updated_at:
        meta["updated_at"] = updated_at
    if stats:
        meta["stats"] = stats

    lines = [
        json.dumps(meta, ensure_ascii=False),
        json.dumps({"type": "missing", "pids": sorted(int(pid) for pid in missing)},
                   ensure_ascii=False),
    ]
    for pid in sorted(products, key=lambda value: int(value)):
        record: dict[str, Any] = {"type": "product"}
        record.update(products[pid])
        lines.append(json.dumps(record, ensure_ascii=False))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
