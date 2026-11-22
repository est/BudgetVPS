# WHMCS 抓取笔记

记录这套 `cart.php` / `feeds` / API 的实测结论，方便以后接新站点时少踩坑。
示例来自 **DediRock**（`billing.dedirock.com`）、**RackNerd**（`my.racknerd.com`）和
**Hosteons**（`my.hosteons.com`）。

WHMCS 下载需要登录，绕过：<https://s3.amazonaws.com/releases.whmcs.com/v2/pkgs/whmcs-8.5.1-release.1.zip>

## 1. 怎么判断一个站点是不是 WHMCS

常见特征：

- `cart.php?a=add&pid=N`、`cart.php?a=confproduct&i=0`
- `clientarea.php`、`index.php?rp=/store/...`
- `includes/api.php`
- `feeds/productsinfo.php`、`feeds/productpricing.php`
- 页面底部或源码里有 WHMCS 版权/模板路径

WHMCS 的 PHP 文件可能是 ionCube 加密的，源码读不到实现，但**文件名和公开文档足够判断有哪些接口**。

## 2. 产品页的三种结果

`cart.php?a=add&pid=N` 大致只有三种走向：

| 结果 | 判断方式 |
| --- | --- |
| 有货 | 200，页面里有 `<div class="product-info">`，能拿到标题、规格、计费周期 |
| 售罄 | 跳转到 `/index.php/store/<分类>/<slug>`，页面含 `Out of Stock` |
| 不存在/下架 | 跳转到 `/index.php/store/<分类>`，没有产品信息 |

注意：

- 请求要带 cookie jar 并跟随 302。`aff.php?aff=...&pid=N` 会先 302 到 `cart.php`，再由 cart 302 到 `cart.php?a=confproduct&i=0`。
- 有些“隐藏/下架”商品在数据库里仍然存在，但 cart 会按“不存在”处理。**cart 才是可订购性的最终标准**。
- 售罄页不一定永远带 `Out of Stock` 文案；如果商品被移到隐藏组，可能直接表现为“无产品”。

## 3. 产品 HTML 结构

典型结构：

```html
<div class="product-info">
    <p class="product-title">1 GB KVM VPS (Black Friday 2026)</p>
    <p>
        1 vCPU Core<br />
        20 GB <strong>PURE SSD</strong> RAID-10 Storage<br />
        1 GB RAM<br />
        3000GB <strong>Monthly</strong> Premium Bandwidth<br />
        1Gbps Public Network Port
    </p>
</div>
```

要点：

- 标题在 `<p class="product-title">`。
- 规格是 `<p>` 里用 `<br />` 分隔的多行，常混有 `<strong>`、`<font>`。
- 有些可配置产品的 `product-info` 是空的，规格全写在标题里，需要回退解析标题。
- 计费周期和价格在：

```html
<select name="billingcycle">
    <option value="monthly"> $5.99 USD Monthly </option>
    <option value="annually"> $71.88 USD Annually </option>
</select>
```

- `billingcycle` 的 value 常见：`monthly`、`quarterly`、`semiannually`、`annually`、`biennially`、`triennially`。
- 价格可能是 `$0.00`（免费）或 `$-1.00`（该周期不可用，主要在 feed 里见到）。

## 4. 解析坑位

### 4.1 Storage 中间夹修饰词

RackNerd 2026 Black Friday 的写法：

```text
20 GB PURE SSD RAID-10 Storage
```

如果正则写成 `20 GB` 后面必须紧跟 `SSD`，就会解析失败。要允许中间出现 `PURE`、`RAID-10` 之类的修饰词，同时保持惰性匹配，避免把 `SATA HDD` 误判成 `HDD`。

### 4.2 流量带千分位

```text
10,000GB Monthly Premium Bandwidth
```

数字部分要允许逗号，否则会解析成 `0 TB`。

### 4.3 RAM 和 Storage 的进位不同

- RAM：`1024 MB = 1 GB`（二进制）
- Storage：`1 TB = 1000 GB`（硬盘厂十进制）

不要用同一套换算，否则 `512 MB` 会变成 `0.51 GB`，`1 TB` 会变成 `1024 GB`。

### 4.4 分数展示

`750 GB` 写成 `¾ TB`，`512 MB` 写成 `½ GB`。全站统一用 unicode 分数，整数不带 `.0`。

### 4.5 CPU 型号里的数字

`1x AMD Ryzen 3900X CPU Core` 这种文本很容易被“数字 + X + CPU”误判成 `3900 vCPU`。
匹配核心数时，`x` 后面最好要求有空白，避免把型号里的 `3900X` 当成倍数。

### 4.6 非标准规格文案

feed/描述里可能遇到：

```text
16GB
250GB SSD or 2TB HDD
4 TB Space
Free Single Monitor. Email only alerts.
```

这些不一定是标准 VPS 规格，解析不出来时宁可留 `—`，不要瞎猜。

### 4.7 数字写在标签后面

Hosteons 的写法：

```text
CPU vCore: 1 (Fair Share)
Dedicated CPU : 8 vCore (Ryzen 5x)
RAM: 7 GB
NVME Disk Space: 120 GB
BANDWIDTH: 7 TB
```

和 RackNerd / DediRock 的“`20 GB SSD Storage` 数字在前”正好相反，正则要单独覆盖：

- CPU：`(?:v?CPU|v?Core)s?\s*(?:Core|Cores)?\s*[:=]\s*(\d+)`
- RAM：`(?:RAM|DDR\d?)\s*[:=]?\s*(\d+)\s*(GB|MB|TB)`（原本的 `RAM_ALT_RE` 就够用）
- Disk：`(SSD|NVME|HDD)\s+(?:Disk|Storage)\s+Space\s*[:=]\s*(\d+)\s*(GB|TB)`
- Traffic：`(?:Bandwidth|Transfer|Traffic|BW)\s*[:=]\s*(\d+)\s*(TB|GB|MB)`

顺序上“标签在前”的模式要先试，再退回原来的模式；否则 `NVME Disk Space: 120 GB` 会被当成解析不出来。

另外注意产品名里的型号别当成 CPU 型号：Hosteons 的 *RYZEN 7 GB* 是套餐档位，不是 CPU，`ryzen\s+\d{1,2}\s*\w+` 这种宽松写法要排除掉 `GB/TB/MB` 结尾。

## 5. 公开 feed：`feeds/productsinfo.php`

这是 WHMCS 自带的前台 widget，不需要登录，很多站点也不挂 Cloudflare。

### 5.1 用法

```text
/feeds/productsinfo.php?pid=968&get=name
/feeds/productsinfo.php?pid=968&get=description
/feeds/productsinfo.php?pid=968&get=price&billingcycle=annually
/feeds/productsinfo.php?pid=968&get=orderurl
/feeds/productsinfo.php?pid=968&get=configoption&configoptionnum=1
```

返回的是 JS，不是 JSON：

```js
document.write('1 GB RAM<br />1x vCore CPU<br />20 GB SSD<br />750 GB Bandwidth');
```

PHP 端用的是 `addslashes`，需要还原 `\'`、`\"`、`\\`、`\0`。

### 5.2 优点

- 不需要 API key。
- 通常不需要过 Cloudflare。
- `get=description` 返回的就是产品页那段规格 HTML，可以直接复用解析逻辑。
- `get=name` 可以用来快速判断 pid 是否存在：不存在返回 `Product ID Not Found`。

### 5.3 坑

- **没有库存字段**：已售罄商品照样返回 name/description/price，无法区分 active / out_of_stock。
- **包含已下架/隐藏商品**：`Retired Product`、`Retired Package`、`Account Ownership Transfer`、隐藏的 `Lite` 等都会返回。直接信 feed 会把它们当成在售。
- **一次只能取一个字段**：一个商品通常要 3–4 次小请求（name、description、annual price，月付还要再试 monthly）。
- **价格按周期分开取**：annual 不可用时返回 `$-1.00`，再试 monthly；两个都没有就回退 cart（cart 还能拿 quarterly 等）。
- **站点可能整段封掉**：RackNerd 的 `/feeds/*` 全部被 LiteSpeed 返回 403，连 `feeds/productpricing.php` 也一样。

### 5.4 `feeds/productpricing.php`

```text
/feeds/productpricing.php?pid=36
```

返回一个 `<form><select>`，每个 option 是“周期 - 每月价格”：

```html
<option value="annually">12 Month Price - $5.99 USD/mo</option>
```

适合快速看有哪些周期，但**每月价格是四舍五入后的展示值**，拿它乘 12 反推年价可能差几美分。要精确总价还是用 `productsinfo.php?get=price&billingcycle=...`。

## 6. 管理员 API：`includes/api.php`

### 6.1 `GetProducts`

```bash
curl -sS -X POST 'https://site/includes/api.php' \
  --data 'action=GetProducts&pid=968&responsetype=json&username=xxx&password=xxx'
```

特点：

- 支持 `pid`，也支持逗号分隔的多个 pid，适合批量。
- 返回 `name`、`description`、`pricing`、`customfields`、`configoptions`。
- `description` 还是那段规格 HTML，不是结构化的 CPU/RAM/Disk 字段。
- `configoptions` 是“可配置选项”（系统、机房、附加服务等），不是规格 bullet。
- 需要管理员 API key / 密码，并且通常要配置 **IP 白名单**。
- 返回值可能是 `{"result":"error","message":"Invalid IP ..."}`，说明 API 开着但当前出口 IP 没被允许。

### 6.2 实测

- DediRock：API 开着，未授权 IP 返回 `Invalid IP`。
- RackNerd：`includes/api.php` 被 Cloudflare 直接 403，连 GET 都不给。

结论：没有管理员凭据时，`GetProducts` 不能当公开抓取接口用。

## 7. Cloudflare 相关

- `cart.php`、`index.php?rp=/store/...`、`includes/api.php` 可能在 Cloudflare 后面。
- `feeds/productsinfo.php` 有时能绕过 Cloudflare（DediRock 可以），有时被源站直接封（RackNerd 是 LiteSpeed 403），有时整个也挂在 challenge 后面（Hosteons）。
- `cf_clearance` 与出口 IP、UA 绑定，不能随便复制到别的机器/CI。
- 本项目用 `curl_cffi` 复用 clearance；需要重新验证时用有头浏览器。
- 本地环境如果挂了 `https_proxy`，`curl_cffi` 可能自动走代理导致 connection reset；必要时 `trust_env=False` 或临时 `env -u https_proxy`。

### 7.1 验证失败别硬刚

“过验证”= 起一次浏览器，这是最重的操作，也是最容易被风控盯上的动作。踩过的坑：

- **每个 pid 各重试 3 次**（旧逻辑）意味着一个被拦的站点一轮能开出几百个浏览器窗口——
  这是在跟 CF 对着干，IP 很容易被重点关注。
- 现在：一轮里最多容忍 5 次验证失败（`CF_MAX_CHALLENGES`），超了**整体跳过该站点**，
  不再发任何请求；`data/<site>.ndjson` 不动，页面继续用上一轮数据。
- 两次真的起浏览器之间至少隔 30 秒（`CF_SOLVE_COOLDOWN`）。刚取到的 clearance 又立刻被拒，
  说明不是 cookie 的问题，再取一次也没用。
- 同一进程内浏览器验证**串行**（`cf.SOLVE_LOCK`），多站点并发时不会同时开两个浏览器。
- `cf_clearance` 通常能撑很久（实测 30 分钟后仍然有效），所以一轮里基本不需要反复取。
- `probe_direct` 直接通时返回的 credentials **不带 solved_at**：这时并没有真的取过 cookie，
  后面万一撞验证要允许立刻起浏览器，别被冷却时间挡住。

### 7.2 别拿关键字扫全文判断“是不是验证页”

真实事故：为了拦住 200 的验证页，一开始写成“body 里出现 `challenge-platform` 就算被拦”，
结果 **Hosteons 的每个正常商品页都被判成验证页**（那串 CF 脚本藏在第 83089 字节处，
正常页面里本来就有），于是每个 pid 都去“重新过验证” → 大量浏览器窗口 → IP 被关注。
症状就是“hosteons 经常触发 cf 验证失败”。

正确做法：

- 403/503：可以用宽泛标记（`Just a moment`、`Attention Required`、`challenge-platform`），
  这个状态码下的 body 本来就是验证页
- 200：只看 **标题是 `Just a moment...`** 且 **整页只有几 KB**（正常商品页 60KB 起，
  标题是 `Shopping Cart - xxx`）

顺带一个好消息：Hosteons 用 `curl_cffi`（chrome131）其实**经常不用 clearance 就能拿到正常页面**，
`probe_direct` 一般直接通过，验证页只是偶尔出现，所以这个站点不需要频繁过验证。

## 8. 本项目的抓取策略

### RackNerd

- 只走 `cart.php` HTML。
- `/feeds/*` 全 403，没有可用公开接口。
- 解析规则要兼容 `20 GB PURE SSD RAID-10 Storage`、`10,000GB` 等写法。

### Hosteons

- 整站（含 `/feeds/*`）都在 Cloudflare managed challenge 后面，走 cart HTML。
- 不过 `curl_cffi`（chrome131）通常**不用 clearance 就能直接拿到正常页面**，`probe_direct` 一般直接过；
  偶尔才撞到验证页，那时才起浏览器。详见 7.2。
- 规格是“标签在前”：`RAM: 7 GB`、`NVME Disk Space: 120 GB`、`BANDWIDTH: 7 TB`，见 4.7。
- 实测 `pid` 到 252 就没了（250 以前大多是 store 页 / 售罄），配置里留到 300，涨了用 `HOSTEONS_MAX_PID` 覆盖。
- 验证失败按 7.1 处理：最多 5 次，超了整体跳过，别把 IP 送上去。

### DediRock

- **历史库里已有的 pid**：优先走 `feeds/productsinfo.php`，拿 name / description / 价格。
- **新 pid**：feed 只查 name；存在则回退 cart 确认是否真的可订购，避免把 `Retired Product` 等加进列表。
- **feed 失败 / 没有 annually+monthly 价格**：回退 cart。
- **库存状态**：feed 没有库存字段，已知商品沿用上一次的 `active` / `out_of_stock`。
- **熔断**：连续 3 次 feed 网络/解析失败后，本轮全部改用 cart。
- **Cloudflare**：feed 站点启动时不预先取 cookie；只有 cart fallback 真撞到 challenge 才取。

这个策略的取舍：feed 一个商品要 3–4 次小请求，比 cart 一次请求多；换来的是不依赖 Cloudflare，以及更准确的描述（例如 768 MB RAM 不会被 cart 四舍五入成 1 GB）。

### 抓取失败的兜底

反爬（Cloudflare 拦死）、站点挂掉、解析全歪，这几种情况都可能让一轮抓取"看起来跑完了、实际上什么都没抓到"。如果照常合并，历史里在售的商品会被整片标成 `stale`，列表就废了。所以：

- **失败判定**（`crawler.round_failed`）：一个成功请求都没有，或者历史里有在售商品却一个都没解析出来。
- **失败时**：`data/<site>.ndjson` 不写，页面直接用上一轮的数据，站点不会从列表里消失。
- **中途落盘只做加法**（`merge_store(mark_stale=False)`）：只写入新抓到的商品，绝不把旧商品标成 `stale` / `out_of_stock`。
- **异常也不放飞**：过 Cloudflare 失败（比如 CI 里浏览器起不来）、站点请求异常，都被 `process_site` 接住，保留上一轮数据并照常渲染。
- 另外 `Fetcher` 会把 **200 但 body 是验证页** 的响应也当成 challenge 抛出去，避免这种页面被误判成"商品没了"。

## 9. 快速探测命令

```bash
# 产品页（带 cookie，跟随跳转）
curl -sSL -c /tmp/cj -b /tmp/cj 'https://site/cart.php?a=add&pid=968'

# feed
curl -sS 'https://site/feeds/productsinfo.php?pid=968&get=name'
curl -sS 'https://site/feeds/productsinfo.php?pid=968&get=description'
curl -sS 'https://site/feeds/productsinfo.php?pid=968&get=price&billingcycle=annually'

# 管理员 API（会暴露是否开了 API / 是否要 IP 白名单）
curl -sS -X POST 'https://site/includes/api.php' \
  --data 'action=GetProducts&pid=968&responsetype=json&username=x&password=x'
```

## 10. 数据口径

- Storage：统一 GB，`1 TB = 1000 GB`
- RAM：统一 GB，`1024 MB = 1 GB`，小于 1 GB 用分数
- Traffic：统一 TB，能写 ¼ / ½ / ¾ 的就写分数
- 价格：优先年付；没有年付就按月价估算年价，并标记 `price_estimated`
- 售罄/下架的历史商品不删除，只改状态，页面上划线
