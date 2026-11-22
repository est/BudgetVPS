# WHMCS 抓取笔记

记录这套 `cart.php` / `feeds` / API 的实测结论，方便以后接新站点时少踩坑。
示例主要来自 **DediRock**（`billing.dedirock.com`）和 **RackNerd**（`my.racknerd.com`）。

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
- `feeds/productsinfo.php` 有时能绕过 Cloudflare（DediRock 可以），有时被源站直接封（RackNerd 是 LiteSpeed 403）。
- `cf_clearance` 与出口 IP、UA 绑定，不能随便复制到别的机器/CI。
- 本项目用 `curl_cffi` 复用 clearance；需要重新验证时用有头浏览器。
- 本地环境如果挂了 `https_proxy`，`curl_cffi` 可能自动走代理导致 connection reset；必要时 `trust_env=False` 或临时 `env -u https_proxy`。

## 8. 本项目的抓取策略

### RackNerd

- 只走 `cart.php` HTML。
- `/feeds/*` 全 403，没有可用公开接口。
- 解析规则要兼容 `20 GB PURE SSD RAID-10 Storage`、`10,000GB` 等写法。

### DediRock

- **历史库里已有的 pid**：优先走 `feeds/productsinfo.php`，拿 name / description / 价格。
- **新 pid**：feed 只查 name；存在则回退 cart 确认是否真的可订购，避免把 `Retired Product` 等加进列表。
- **feed 失败 / 没有 annually+monthly 价格**：回退 cart。
- **库存状态**：feed 没有库存字段，已知商品沿用上一次的 `active` / `out_of_stock`。
- **熔断**：连续 3 次 feed 网络/解析失败后，本轮全部改用 cart。
- **Cloudflare**：feed 站点启动时不预先取 cookie；只有 cart fallback 真撞到 challenge 才取。

这个策略的取舍：feed 一个商品要 3–4 次小请求，比 cart 一次请求多；换来的是不依赖 Cloudflare，以及更准确的描述（例如 768 MB RAM 不会被 cart 四舍五入成 1 GB）。

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
