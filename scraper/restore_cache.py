"""把 GitHub Actions cache 里的 data 和仓库 HEAD 里的版本逐站点比对。

cache 是为了"意外中断下次继续"，但它可能比仓库里的旧（比如上一轮 cache 没存上、
但数据已经提交了）。所以恢复后不能无脑覆盖，逐个 ndjson 看 meta.updated_at，
谁新用谁；一样新时用 cache，因为它可能带着半程游标（progress）。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def updated_at(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") == "meta":
            return str(record.get("updated_at") or "")
    return ""


def _moment(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return EPOCH


def newest(cached: str, head: str) -> str:
    """两份 ndjson，返回该保留的那份。"""
    if _moment(updated_at(cached)) >= _moment(updated_at(head)):
        return cached
    return head


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="合并 Actions cache 和仓库里的 data")
    parser.add_argument("--cache-dir", default="data", help="从 cache 恢复出来的目录")
    parser.add_argument(
        "--head-dir", default="", help="仓库 HEAD 里的 data 目录（为空表示不比较）"
    )
    args = parser.parse_args(argv)

    cache_dir = Path(args.cache_dir)
    head_dir = Path(args.head_dir) if args.head_dir else None
    if not cache_dir.exists():
        print("[cache] 没有缓存数据，跳过")
        return 0
    if head_dir is None or not head_dir.exists():
        print("[cache] 没有 HEAD 版本可比较，直接使用缓存数据")
        return 0

    for path in sorted(cache_dir.glob("*.ndjson")):
        head_path = head_dir / path.name
        if not head_path.exists():
            print(f"[cache] {path.name}：HEAD 里没有，使用缓存")
            continue
        cached = path.read_text(encoding="utf-8")
        head = head_path.read_text(encoding="utf-8")
        if newest(cached, head) is head:
            path.write_text(head, encoding="utf-8")
            print(f"[cache] {path.name}：仓库版本更新，回退到 HEAD")
        else:
            print(f"[cache] {path.name}：缓存版本更新，保留缓存")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
