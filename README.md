# Budget VPS 价格表

答案：是的，绝大多数"廉价 VPS 商家"用的都是同一套 **WHMCS** 账单系统（`cart.php?a=add&pid=N`、`clientarea.php`、`index.php/store/...` 这些 URL 就是标志）。所以只要按 `pid` 顺序遍历，就能把整站套餐、配置和价格都扫出来。

这个项目就是干这个的：

- 从 `pid=1` 开始顺序扫描 WHMCS 购物车，请求间隔默认 2.5–4 秒（可调，别把人家站点打挂）
- 解析 **Name / CPU / RAM / SSD / Traffic / Price(per year)**
- 生成 Markdown 表格 + 一个可搜索、可排序的静态页面
- GitHub Actions 每天定时抓取并部署到 GitHub Pages

> 示例站点：<https://billing.dedirock.com/aff.php?pid=265>（pid=265 当前已售罄，售罄商品 WHMCS 不展示配置，表格里只会保留在售套餐）

## 页面长什么样

抓取完成后会生成：

| 文件 | 用途 |
| --- | --- |
| `docs/index.html` | GitHub Pages 主页（搜索 / 排序 / 深色表格） |
| `docs/index.md` | 纯 Markdown 表格 |
| `docs/data.json` | 原始结构化数据，方便二次加工 |
| `data/products.json` | 历史库（含已下架 / 售罄商品，按 pid 归档） |

## 本地运行

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 全量扫描（默认 1..400，间隔 2.5-4s，大约 30-40 分钟）
.venv/bin/python -m scraper.main

# 先小范围试水
.venv/bin/python -m scraper.main --min-pid 1 --max-pid 30 --delay-min 1 --delay-max 2

# 只重新渲染，不抓取
.venv/bin/python -m scraper.main --no-crawl
```

第一次运行会**弹出一个真实的 Chrome/Edge 窗口**过 Cloudflare 验证（几秒钟），拿到 `cf_clearance` 后写进 `data/.cookies.json`，后续请求全部走 `curl_cffi`，不再需要浏览器。cookie 默认复用 20 分钟。

### Cloudflare 说明

站点开了 Cloudflare managed challenge：

- 纯 `curl` / `requests` / 无头浏览器都会卡在 `Just a moment...`
- 真实有头浏览器 + `curl_cffi` 复用 cookie 是最省事的组合
- 如果出口 IP 没被挑战，脚本会跳过浏览器直接抓（`probe_direct`）
- cookie 与出口 IP、UA 绑定，所以不能直接把本地的 cookie 拿去 CI 用
- GitHub Actions 里用 `xvfb-run` 起**有头** Chrome（工作流已经配好）
- 如果 CI 的机房 IP 被 Cloudflare 重点照顾，可以在仓库 Secrets 里放一个手动取得的 `CF_CLEARANCE`

手动取一次 clearance（输出 JSON）：

```bash
.venv/bin/python -m scraper.cf https://billing.dedirock.com
```

## 配置

全部可以用命令行参数或环境变量覆盖：

| 参数 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--base-url` | `BASE_URL` | `https://billing.dedirock.com` | 换成任意 WHMCS 站点即可复用 |
| `--min-pid` | `MIN_PID` | `1` | 起始 pid |
| `--max-pid` | `MAX_PID` | `400` | 结束 pid |
| `--delay-min` | `DELAY_MIN` | `2.5` | 最小请求间隔（秒） |
| `--delay-max` | `DELAY_MAX` | `4.0` | 最大请求间隔（秒） |
| `--cf-cache-minutes` | `CF_CACHE_MINUTES` | `20` | clearance 复用时长 |
| | `TRUST_ENV_PROXY` | `0` | 设为 `1` 时沿用环境变量里的 `http(s)_proxy` |
| `--force-solve` | | | 忽略缓存，强制重新过验证 |
| `--no-crawl` | | | 只渲染已有数据 |

`pid` 之间会有大量空洞（下架商品、未启用分类等），属于正常现象；扫描范围按站点实际情况调整。

## 部署到 GitHub Pages

1. 推到 GitHub 后，进入 **Settings → Pages**，把 Source 设为 **GitHub Actions**
2. 打开 **Actions** 手动跑一次 `Scrape VPS & Deploy Pages`（之后每天 UTC 02:23 自动跑）
3. 站点地址形如 `https://<user>.github.io/<repo>/`

工作流会：

1. `xvfb-run` 起有头 Chrome 过 Cloudflare，拿 clearance
2. 按 pid 慢速扫描，合并进 `data/products.json`
3. 重新生成 `docs/`
4. 把数据 commit 回仓库
5. 部署 `docs/` 到 Pages

## 解析规则

- **Name**：产品页的 `p.product-title`
- **CPU**：`1x vCore CPU` / `4 cores` → `N vCPU`，顺带识别 `E3-1230v3`、`Ryzen` 等型号
- **RAM**：`32GB RAM` → `32 GB`
- **SSD**：`250GB SSD` / `2x 1TB NVMe` → 原样保留数量与介质
- **Traffic**：`1 TB Monthly Bandwidth` / `10TB BW` / `Unmetered`
- **Price(per year)**：优先取年付价；只有月付时按 `×12` 估算，页面上用 `*` 标注

## 注意

- 请保持较低频率，默认间隔已经比较保守；不要把 `--delay-min` 调到 1 秒以下长期跑
- 只抓公开的商品页，不登录、不下单、不碰任何用户数据
- 售罄商品 WHMCS 不返回配置和价格，所以只能记录"曾经存在"，无法补全
- 站点改主题 / 换字段时，解析规则集中在 `scraper/parse.py`，改一处即可
