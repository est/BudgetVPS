# Budget VPS 价格表

**在线页面：<https://est.github.io/BudgetVPS/>**

答案：是的，绝大多数"廉价 VPS 商家"用的都是同一套 **WHMCS** 账单系统（`cart.php?a=add&pid=N`、`clientarea.php`、`index.php/store/...` 这些 URL 就是标志）。所以只要按 `pid` 顺序遍历，就能把整站套餐、配置和价格都扫出来。

这个项目就是干这个的：

- 从 `pid=1` 开始顺序扫描 WHMCS 购物车，请求间隔默认 2.5–4 秒（可调，别把人家站点打挂）
- 解析 **Name / CPU / RAM / Storage / Traffic / Price(per year)**
- 生成 Markdown 表格 + 一个可搜索、可排序、可按商家筛选的静态页面
- GitHub Actions 每天定时抓取并部署到 GitHub Pages
- 多站点：**DediRock**（`billing.dedirock.com`，aff=1033）、**RackNerd**（`my.racknerd.com`，aff=1865）

> 售罄商品 WHMCS 不返回配置和价格，所以**有历史数据**的商品即使这一轮售罄（`out_of_stock`）或页面已无产品（`stale`，可能已下架），也不会从表格里删掉，只整行划删除线表示本轮不可用；在售排在前面，划线的排在后面。从来没扫到过数据的 pid 依然不出现。

## 文件结构

| 文件 | 用途 |
| --- | --- |
| `data/<site>.ndjson` | 每个站点一份数据：第 1 行 meta、第 2 行 missing、其余每行一个产品 |
| `templates/index.html` | 页面模板，`{{...}}` 占位符在构建时替换 |
| `_site/` | 构建产物（`index.html` / `index.md` / `data.json`），**不入库** |
| `scraper/sites.py` | 站点配置：名称、URL、aff 参数、`max_pid`、是否挂 Cloudflare |
| `scraper/crawler.py` | pid 扫描、重试、时间预算、续采游标、历史合并 |
| `scraper/parse.py` | WHMCS 页面解析、单位换算 |
| `scraper/store.py` | NDJSON 读写 |
| `scraper/render.py` | Markdown / HTML / data.json 生成 |
| `scraper/restore_cache.py` | CI 里比对 Actions cache 与仓库 HEAD 的 data，留新的 |
| `scraper/main.py` | CLI 入口、并发调度 |

## 本地运行

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 全量抓取所有站点（不同站点并发；单站 2.5-4s 间隔，最多 50 分钟就收工）
.venv/bin/python -m scraper.main

# 只抓某个站点 / 小范围试水
.venv/bin/python -m scraper.main --site racknerd
.venv/bin/python -m scraper.main --site dedirock --min-pid 1 --max-pid 30 --delay-min 1 --delay-max 2

# 限时 10 分钟，到点保存已采数据，下次接着采
.venv/bin/python -m scraper.main --budget-minutes 10

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
| | `<SITE>_MAX_PID` | 站点配置 | 单独覆盖某个站的结束 pid（如 `RACKNERD_MAX_PID`），优先级低于 `MAX_PID` |
| `--delay-min` | `DELAY_MIN` | 站点配置 | 最小请求间隔（秒） |
| `--delay-max` | `DELAY_MAX` | 站点配置 | 最大请求间隔（秒） |
| `--cf-cache-minutes` | `CF_CACHE_MINUTES` | `20` | clearance 复用时长 |
| `--budget-minutes` | `CRAWL_BUDGET_MINUTES` | `50` | 整轮抓取的时间预算，到点收工并保存已采数据，`0` 表示不限时 |
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
懒得改代码的话，在 Actions 里设 `RACKNERD_MAX_PID=1200` 这样的环境变量即可（见上表）。

> RackNerd 的坑：2026 Black Friday 已经用到 `pid=968`，而旧配置 `max_pid=280`，
> 281~979 整段从来没扫过——不是 pid 跳跃的问题，是上限设小了。

### 采不完怎么办（时间预算 + 续采）

`max_pid` 调大之后一轮可能扫不完（RackNerd 1..1000 串行要 50+ 分钟），所以有这套机制：

- 到 `--budget-minutes` 就**主动收工**，不是被 CI 掐死：已采到的数据照常合并保存、照样提交，
  页面照常发布，只是顶栏会多一个「本轮未采完」的提示
- 每个站点在 `data/<site>.ndjson` 里记一条 `progress`：
  `{"next_pid": 962, "complete": false, ...}` 表示下次从 962 接着采
- **采完了**（`complete: true`）下次就从 `min_pid` 重新全量复查一遍，等于保证"最后一定是完整的"
- 抓取过程中每 25 个 pid 还会**中途落盘**一次，被硬杀也不会丢掉已采的部分
- 只有**这一轮真正请求过**的 pid 才会被改状态，所以续采不会把没轮到的在售商品误标成下架

### 并发

不同供应商之间是**并发**采集的（一个站点一个线程），各自保持自己的请求间隔，互不影响。
同一个站点内部仍然是串行的，不会因为并发而加大对单个站点的压力。
某个站点抛异常不会影响其它站点，已落盘的检查点都还在。

### GitHub Actions 里怎么续采

工作流会：

1. 用 `actions/cache` 把上一轮的 `data/` 恢复出来（`restore-keys: vps-data-` 取最近一次）
2. 和仓库 HEAD 里的 `data/` **逐站点比 `updated_at`**，留新的那份，避免旧缓存把已提交的数据覆盖回去
3. 抓取（`CRAWL_BUDGET_MINUTES=55`，作业硬超时 120 分钟只是兜底）
4. 先 `actions/cache/save` 再提交数据，所以提交步骤挂掉也不会丢进度
5. 提交消息带上各站在售数量，例如 `chore(data): 2026-11-21 抓取结果` + `DediRock 43 在售，RackNerd 40 在售`

## 单位口径

- **RAM** 统一换算成 **GB**，且按**二进制进位**（`1024 MB` → `1 GB`，不是 `1.02 GB`；`512 MB` → `½ GB`、`768 MB` → `¾ GB`）。`< 1 GB` 能落成 `¼ ½ ¾` 这类的用 unicode 分数，`≥ 1 GB` 保留小数、只去掉整数值的尾零（`2.0 GB` → `2 GB`，`2.5 GB` 仍是 `2.5 GB`）
- **Storage** 统一换算成 **GB**（`1 TB` → `1000 GB`，`512 MB` → `0.51 GB`），保留介质（SSD / NVMe / HDD）和数量（`2 × 1000 GB SSD`）。注意硬盘是十进制标称，所以这里 ÷1000，和 RAM 的 ÷1024 不同
- **Traffic** 统一换算成 **TB**，能写成分数就用分数（`750 GB` → `¾ TB`、`500 GB` → `½ TB`、`1500 GB` → `1½ TB`），否则保留两位小数（`110 GB` → `0.11 TB`）；`Unmetered` 原样保留
- **Price(per year)** 优先取 WHMCS 的年付价；只有月付时按 `×12` 估算，页面上用 `*` 标注

## 排序

点表头切换升降序，所有列都按**数值**或**自然序**排，不是字典序：

- **RAM / Storage / Traffic / PID / Price** 走 `data-sort` 数值排序：`½ GB` 排在 `1 GB` 前面，
  `2 × 1000 GB SSD` 按 `2000` 排而不是按字面的 `2`，`pid 2` 排在 `pid 10` 前面
- **Name / CPU** 走 natural sort（`localeCompare` 的 `numeric: true`）：`2GB` 排在 `10GB` 前面
- 没有数值的（`—`、`Unmetered`、缺价格）无论升降序一律排最后，不会被当成 `0` 混进正常数据

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
2. 打开 **Actions** 可以手动跑一次 `Scrape VPS & Deploy Pages`（之后每天 UTC 20:00 自动跑）
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
