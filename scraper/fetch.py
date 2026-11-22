"""HTTP 抓取层：curl_cffi + Cloudflare clearance cookie。"""

from __future__ import annotations

from typing import Any

from curl_cffi import requests

from .cf import looks_like_challenge
from .config import trust_env_proxy


class ChallengeError(RuntimeError):
    """Cloudflare 又弹验证了，需要重新取 cookie。"""


class Fetcher:
    def __init__(self, base_url: str, credentials: dict[str, Any]) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session(
            impersonate="chrome131", trust_env=trust_env_proxy()
        )
        self.session.headers.update(
            {
                "User-Agent": credentials["user_agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        self.session.cookies.update(credentials["cookies"])

    def get(self, path: str, timeout: float = 45.0) -> requests.Response:
        url = path if path.startswith("http") else self.base_url + path
        resp = self.session.get(url, timeout=timeout, allow_redirects=True)
        # 有时 Cloudflare 用 200 返回验证页，body 里照样是挑战标记；
        # 这种页面解析不出任何产品，绝不能当成"商品本轮没抓到"。
        if looks_like_challenge(resp.text):
            raise ChallengeError(f"Cloudflare challenge on {url} ({resp.status_code})")
        return resp

    def update_credentials(self, credentials: dict[str, Any]) -> None:
        self.session.headers["User-Agent"] = credentials["user_agent"]
        self.session.cookies.update(credentials["cookies"])
