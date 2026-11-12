"""Cloudflare clearance helper.

WHMCS 后台大多挂在 Cloudflare 后面，纯 curl_cffi 请求会拿到
"Just a moment..." 的 managed challenge。这里用真实浏览器过一次验证，
把 cf_clearance 等 cookie 取出来交给 curl_cffi 复用，之后爬取只走 HTTP，
又快又不容易被风控。

注意：cf_clearance 和出口 IP / User-Agent 绑定，所以：
  * 本地跑：直接开一个真实的 Chrome/Edge 窗口，几秒就过。
  * GitHub Actions：用 xvfb-run 起有头 Chrome（无头会被识别）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

CHALLENGE_MARKERS = (
    "Just a moment",
    "Performing security verification",
    "cf-chl",
    "challenge-platform",
    "Attention Required",
)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_CANDIDATES = (
    os.getenv("CHROME_PATH"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
)


def looks_like_challenge(html: str) -> bool:
    head = html[:6000]
    return any(marker in head for marker in CHALLENGE_MARKERS)


def find_browser() -> str | None:
    for candidate in BROWSER_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_devtools(port: int, timeout: float = 15.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=1
            ) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def solve(base_url: str, timeout: float = 90.0, headless: bool | None = None) -> dict[str, Any]:
    """打开真实浏览器过 Cloudflare 验证，返回 cookies 和 UA。"""
    from playwright.sync_api import sync_playwright

    exe = find_browser()
    if not exe:
        raise RuntimeError(
            "找不到 Chrome/Edge，可用 CHROME_PATH 环境变量指定浏览器路径"
        )

    port = _free_port()
    profile = Path(tempfile.mkdtemp(prefix="budgetvps-chrome-"))
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1366,900",
        "about:blank",
    ]

    if headless is None:
        # Linux 上没有 DISPLAY 时只能无头（成功率低，CI 里请用 xvfb-run）
        headless = sys.platform.startswith("linux") and not os.environ.get("DISPLAY")
    if headless:
        args.insert(1, "--headless=new")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.insert(1, "--no-sandbox")
    elif os.getenv("CI"):
        # GitHub Actions 的容器里 Chrome 经常也需要关沙箱
        args.insert(1, "--no-sandbox")

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        if not _wait_for_devtools(port):
            raise RuntimeError("浏览器启动失败（DevTools 端口没起来）")

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()

            root = base_url.rstrip("/")
            last_error: Exception | None = None
            for path in ("/index.php/store", "/cart.php?a=add&pid=1", "/"):
                try:
                    page.goto(root + path, wait_until="domcontentloaded", timeout=60_000)
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    page.wait_for_timeout(1000)
            if last_error is not None:
                raise RuntimeError(f"打不开 {root}: {last_error}")

            deadline = time.time() + timeout
            cleared = False
            while time.time() < deadline:
                try:
                    html = page.content()
                    title = page.title()
                except Exception:
                    page.wait_for_timeout(1500)
                    continue
                cookies = {c["name"]: c["value"] for c in context.cookies()}
                if (
                    "cf_clearance" in cookies
                    and "Just a moment" not in title
                    and not looks_like_challenge(html)
                ):
                    cleared = True
                    break
                page.wait_for_timeout(2000)

            ua = page.evaluate("navigator.userAgent")
            # 全新 profile，拿到的 cookie 都属于目标站点
            cookies = {c["name"]: c["value"] for c in context.cookies()}

            if not cleared:
                raise RuntimeError(
                    "Cloudflare 验证没通过（可能被判定为机器人或 IP 被拦）。"
                    "本地可重试；CI 请确认用 xvfb-run 起有头浏览器，或配置代理。"
                )

            try:
                browser.close()
            except Exception:
                pass
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    return {
        "solved_at": int(time.time()),
        "user_agent": ua,
        "cookies": cookies,
    }


def load_credentials(path: Path, max_age: float = 20 * 60) -> dict[str, Any] | None:
    """读取本地缓存的 clearance，默认 20 分钟内复用。"""
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if time.time() - data.get("solved_at", 0) > max_age:
        return None
    if not data.get("cookies"):
        return None
    return data


def save_credentials(path: Path, creds: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(creds, indent=2, ensure_ascii=False))


def probe_direct(base_url: str, timeout: float = 30.0) -> bool:
    """先试试不带头也能不能直接拿到页面（有些 IP 不会被 CF 挑战）。"""
    from curl_cffi import requests as curl_requests

    from .config import trust_env_proxy

    try:
        with curl_requests.Session(
            impersonate="chrome131", trust_env=trust_env_proxy()
        ) as session:
            resp = session.get(
                base_url.rstrip("/") + "/cart.php?a=add&pid=1",
                headers={"User-Agent": DEFAULT_UA},
                timeout=timeout,
            )
    except Exception:
        return False
    return resp.status_code == 200 and not looks_like_challenge(resp.text)


def get_credentials(
    base_url: str,
    cache_path: Path,
    max_age: float = 20 * 60,
    force: bool = False,
) -> dict[str, Any]:
    """优先用环境变量 CF_COOKIE / 本地缓存，否则起浏览器现取。"""
    env_cookie = os.getenv("CF_CLEARANCE") or os.getenv("CF_COOKIE")
    if env_cookie:
        cookies = {"cf_clearance": env_cookie}
        raw = os.getenv("CF_COOKIE_JSON")
        if raw:
            try:
                cookies.update(json.loads(raw))
            except Exception:
                pass
        return {
            "solved_at": int(time.time()),
            "user_agent": os.getenv("CF_USER_AGENT") or DEFAULT_UA,
            "cookies": cookies,
        }

    if not force:
        cached = load_credentials(cache_path, max_age=max_age)
        if cached:
            return cached
        if probe_direct(base_url):
            print("[cf] 直接请求就通了，不需要浏览器", flush=True)
            return {
                "solved_at": int(time.time()),
                "user_agent": DEFAULT_UA,
                "cookies": {},
            }

    print("[cf] 正在用浏览器过 Cloudflare 验证…", flush=True)
    creds = solve(base_url)
    save_credentials(cache_path, creds)
    print(f"[cf] 验证通过，拿到 {len(creds['cookies'])} 个 cookie", flush=True)
    return creds


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://billing.dedirock.com"
    print(json.dumps(solve(target), indent=2, ensure_ascii=False))
