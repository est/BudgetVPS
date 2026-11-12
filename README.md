# Budget VPS 价格表

**在线页面：<https://est.github.io/BudgetVPS/>**

答案：是的，绝大多数"廉价 VPS 商家"用的都是同一套 **WHMCS** 账单系统（`cart.php?a=add&pid=N`、`clientarea.php`、`index.php/store/...` 这些 URL 就是标志）。所以只要按 `pid` 顺序遍历，就能把整站套餐、配置和价格都扫出来。

这个项目就是干这个的：

- 从 `pid=1` 开始顺序扫描 WHMCS 购物车，请求间隔默认 2.5–4 秒（可调，别把人家站点打挂）
- 解析 **Name / CPU / RAM / Storage / Traffic / Price(per year)**
- 生成 Markdown 表格 + 一个可搜索、可排序、可按商家筛选的静态页面
- GitHub Actions 每天定时抓取并部署到 GitHub Pages
- 多站点：**DediRock**（`billing.dedirock.com`，aff=1033）、**RackNerd**（`my.racknerd.com`，aff=1865）

> 售罄商品 WHMCS 不返回配置和价格，表格里只会保留在售套餐。

## 文件结构

| 文件 | 用途 |
| --- | --- |
| `data/<site>.ndjson` | 每个站点一份数据：第 1 行 meta、第 2 行 missing、其余每行一个产品 |
| `templates/index.html` | 页面模板，`{{...}}` 占位符在构建时替换 |
| `_site/` | 构建产物（`index.html` / `index.md` / `data.json`），**不入库** |
| `scraper/sites.py` | 站点配置：名称、URL、aff 参数、`max_pid`、是否挂 Cloudflare |
| `scraper/crawler.py` | pid 扫描、重试、历史合并 |
| `scraper/parse.py` | WHMCS 页面解析、单位换算 |
| `scraper/store.py` | NDJSON 读写 |
| `scraper/render.py` | Markdown / HTML / data.json 生成 |
| `scraper/main.py` | CLI 入口 |

## 本地运行

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 全量抓取所有站点（默认 2.5-4s 间隔，大约 30-40 分钟）
.venv/bin/python -m scraper.main

# 只抓某个站点 / 小范围试水
.venv/bin/python -m scraper.main --site racknerd
.venv/bin/python -m scraper.main --site dedirock --min-pid 1 --max-pid 30 --delay-min 1 --delay-max 2

# 只重新渲染，不抓取
.venv/bin/python -m scraper.main --no-crawl

# 改了正则之后，用已保存的 specs_raw 重新解析字段（不联网）
.venv/bin/python -m scraper.main --reparse
```

第一次运行会**弹出一个真实的 Chrome/Edge 窗口**过 Cloudflare 验证（几秒钟），拿到 `cf_clearance` 后写进 `data/.cookies-<site>.json`，后续请求全部走 `curl_cffi`，不再需要浏览器。cookie 默认复用 20 分钟。

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
| `--site` | `SITE` | `all` | 站点 id，逗号分隔（`dedirock` / `racknerd`） |
| `--min-pid` | `MIN_PID` | `1` | 起始 pid |
| `--max-pid` | `MAX_PID` | `0` | 结束 pid，`0` 表示用站点配置的 `max_pid` |
| `--delay-min` | `DELAY_MIN` | 站点配置 | 最小请求间隔（秒） |
| `--delay-max` | `DELAY_MAX` | 站点配置 | 最大请求间隔（秒） |
| `--cf-cache-minutes` | `CF_CACHE_MINUTES` | `20` | clearance 复用时长 |
| | `TRUST_ENV_PROXY` | `0` | 设为 `1` 时沿用环境变量里的 `http(s)_proxy` |
| `--force-solve` | | | 忽略缓存，强制重新过验证 |
| `--no-crawl` | | | 只渲染已有数据 |
| `--reparse` | | | 用 `specs_raw` 重新解析字段 |

### 扫描范围与跳过逻辑

`pid` 之间会有大量空洞（下架商品、未启用分类等），属于正常现象：

- 上一次扫描确认**中间**是空洞的 pid，本次直接跳过，不再请求
- **尾部**（最后一个已知商品之后）的连续空洞仍然每次复查，新商品一般只会出现在尾部
- 售罄商品不算空洞，每次都会复查是否补货

想扩大尾部复查范围就调大站点配置的 `max_pid`；新增商品超过 `max_pid` 时记得同步调整。

## 单位口径

- **Storage** 统一换算成 **GB**（`1 TB` → `1000 GB`，`512 MB` → `0.51 GB`），保留介质（SSD / NVMe / HDD）和数量（`2 × 1000 GB SSD`）
- **Traffic** 统一换算成 **TB**，能写成分数就用分数（`750 GB` → `¾ TB`、`500 GB` → `½ TB`、`1500 GB` → `1½ TB`），否则保留两位小数（`110 GB` → `0.11 TB`）；`Unmetered` 原样保留
- **Price(per year)** 优先取 WHMCS 的年付价；只有月付时按 `×12` 估算，页面上用 `*` 标注

## 添加新站点

在 `scraper/sites.py` 里加一条即可（所有 WHMCS 站点通用）：

```python
"example": Site(
    id="example",
    name="Example",
    base_url="https://billing.example.com",
    crawl_path="/cart.php?a=add&pid={pid}",   # 扫描用（别加 aff 之外的副作用）
    link_path="/aff.php?aff=12345&pid={pid}",  # 表格里展示 / 跳转用
    max_pid=200,
    cloudflare=True,
),
```

## 部署到 GitHub Pages

1. 推送到 GitHub，工作流会自动开启 Pages（`configure-pages` 的 `enablement: true`），不用手动点 Settings
2. 打开 **Actions** 可以手动跑一次 `Scrape VPS & Deploy Pages`（之后每天 UTC 02:23 自动跑）
3. 站点地址形如 `https://<user>.github.io/<repo>/`（本项目是 <https://est.github.io/BudgetVPS/>）

工作流会：

1. `xvfb-run` 起有头 Chrome 过 Cloudflare，拿 clearance
2. 按 pid 慢速扫描各站点，合并进 `data/<site>.ndjson`
3. 用 `templates/index.html` 生成 `_site/` 静态页
4. 把数据 commit 回仓库
5. 部署 `_site/` 到 Pages

## 解析规则

- **Name**：产品页的 `p.product-title`
- **CPU**：`1x vCore CPU` / `4 cores` → `N vCPU`，顺带识别 `E3-1230v3`、`Ryzen` 等型号
- **RAM**：`32GB RAM` → `32 GB`
- **Storage**：`250GB SSD` / `2x 1TB NVMe` → 统一 GB，保留数量与介质
- **Traffic**：`1 TB Monthly Bandwidth` / `1000GB Premium Bandwidth` / `10TB BW` / `Unmetered`
- **Price(per year)**：优先取年付价；只有月付时按 `×12` 估算，页面上用 `*` 标注

## 注意

- 请保持较低频率，默认间隔已经比较保守；不要把 `--delay-min` 调到 1 秒以下长期跑
- 只抓公开的商品页，不登录、不下单、不碰任何用户数据
- 站点改主题 / 换字段时，解析规则集中在 `scraper/parse.py`，改一处即可
