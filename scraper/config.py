"""运行期小配置。"""

from __future__ import annotations

import os


def trust_env_proxy() -> bool:
    """是否沿用环境变量里的 http(s)_proxy。

    默认关闭：很多人本地有个半死不活的代理变量，会让 curl_cffi 直接超时。
    需要走代理时设置 TRUST_ENV_PROXY=1。
    """
    return os.getenv("TRUST_ENV_PROXY", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
