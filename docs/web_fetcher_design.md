# MatLens 网页/文献抓取能力设计（2026-10-15）

## 一句话

给 Agent 补上「搜到文献 → **拿到正文** → 沉淀进库」这条闭环里缺失的抓取环节，
**在合规边界内**做到尽可能强的抓取能力。

## 一、先说不做什么（不可妥协）

用户最初提出「反追踪能力」，并指向 crawl4ai 的 `enable_stealth`、undetected-browser、
代理池轮换。**这些一律不接入**。

### crawl4ai 的 stealth 解决的是另一个问题（2026-10-15 澄清）

| | stealth / undetected | 反追踪（我们要的） |
|---|---|---|
| 方向 | 对站点隐藏「我是爬虫」 | 对站点隐藏「我们是谁」 |
| 效果 | 绕过站点反爬检测 | 防止被建立身份画像 |
| 是否解决 IP | ❌ 换指纹，服务器照样看到 IP | ❌ 同左，IP 属网络层 |
| 副作用 | 用真实浏览器指纹却不执行 JS、不产生 cookie、间隔规律 → **「像人又不像人」反而更异常** | 减少可关联字段 |

站点看到 UA 是 `MatLens/0.1` 还是 `Chrome`，对「我们是谁」的保护力度是一样的。

### 明确不做的清单（代码里写死 + 测试守着）

```python
REFUSED_TECHNIQUES = (
    "undetected-chromedriver / playwright-stealth 指纹伪装",
    "验证码 OCR 与滑块破解",
    "付费墙 cookie 注入与内容盗取",
    "代理池轮换以规避 IP 封禁",
    "伪造 Referer / 登录态绕过机构访问控制",
    "抓取知网 / 维普 / 超星等明令禁止的站点（见 BLOCKED_SITES）",
)
```

`web_fetcher.fetch()` 的签名里**没有任何** stealth/headless/proxy/bypass/cookie 参数
—— 这是有意的：绕过能力不应该存在于产品接口里。

---

## 一之二、明令禁止的站点（BLOCKED_SITES）

**8 个域名硬拦**，在 robots 检查**之前**生效：

```python
BLOCKED_SITES = {
    "cnki.net": "...", "cnki.com.cn": "...",
    "cqvip.com": "...", "cqvip.cn": "...",
    "wanfangdata.com.cn": "...",
    "chaoxing.com": "...", "duxiu.com": "...", "duxiu.net": "...",
}
```

**为什么放在 robots 之前**：知网首页 robots 是允许的，但**服务条款的效力高于
robots 文件** —— robots 只是技术层的一层，不能替代条款授权。

每条都写明原因与替代路径（官网人工检索 → 导出 Refworks/EndNote 题录 → 知识库导入）。

边界处理：子域也拦（`sub.deep.cnki.net`）；相似域名不误杀（`x.com/cnki.net.evil.com` 放行）。

## 一之三、反追踪：实际做到了什么

用户澄清「反追踪 = 抓取时保护我们自己的 IP/身份不被追踪」。已落地：

### HTTP 层（代码可控，全部已阻断）

| 追踪向量 | 处理 |
|---|---|
| User-Agent 泄露身份 | 去标识化：`MatLens/0.1 (academic research crawler)`，**无邮箱/无 GitHub/无本机路径**。早期版本 `(+https://github.com/…; mailto:…)` 等于每次抓取都把「谁在抓」递给对方 |
| Referer | **不发**。抓文献是我们主动访问，没有真实来源页，编一个比不发更糟 |
| Origin | **不发**（非 CORS 场景无意义） |
| Cookie / 登录态 | **绝不使用**。`_build_opener()` 显式构造且不装 `HTTPCookieProcessor` —— 装了就会被保留并带回，跨请求关联立刻成立 |
| 浏览器指纹头 | **不发** `sec-ch-ua` 等。我们不是浏览器，不伪造特征 |
| X-Forwarded-For | **不发**，不泄露本机 IP 链路 |
| 本地磁盘痕迹 | `_mask_url()` 剥 query / fragment / **userinfo**（userinfo 可能含用户名密码） |

`test_no_cookie_processor_in_opener` 和 `test_headers_minimalised` 守着这些不被改回去。

### 网络层（代码控不了，如实告知）

服务器在 **TCP 层**就能看到出口 IP 和 ASN，改 UA/换指纹都改变不了 —— 这是物理事实。

`privacy_report()` 如实报告：
- `MATLENS_WEB_PROXY` 未配置 → 「目标站点看到的是你的本机出口 IP」
- 配置方法：`export MATLENS_WEB_PROXY=socks5h://127.0.0.1:9150`
  （用 **socks5h** 而非 socks5 —— h 表示由代理端做 DNS 解析，避免本地 DNS 泄露真实查询的域名）
- 即便用 Tor 也**不是绝对匿名**（全局被动监听、目标站点自身仍可做时间线关联）

`honest_bottom_line` 原文：

> 代码能消除「可关联的痕迹」（HTTP 层身份、会话、磁盘记录），这是本模块做到的。
> 要隐藏 IP 必须走网络层（Tor / VPN / 代理），没有任何代码能替代。所以
> **「黑客也无法追踪」这个承诺，我不会给 —— 给了就是不负责任。**

---

## 一之四、代理：一个差点造成安全假象的坑（重要）

### urllib 根本不支持 socks5

`urllib.request.ProxyHandler` 的协议键**只有 `http` / `https`**：

```python
>>> list(urllib.request.ProxyHandler().proxies.keys())
['https', 'http']
```

传 `socks5://127.0.0.1:9050` 会被当作未知协议**静默忽略**，opener 照常直连 ——
**用户以为配好了 Tor，实际在裸奔，且没有任何报错**。这是最危险的一类 bug：
保护措施看起来生效了。

### 现在的行为

| 配置 | 结果 |
|---|---|
| `socks5://` / `socks5h://` / `socks4://` | 走 PySocks（`socks.create_connection` 建隧道 + `http.client` 复用） |
| PySocks 缺失 或 代理不可达 | **显式抛错，绝不静默改直连** |
| `http://` / `https://` | urllib 原生 ProxyHandler |
| 非法协议 | `ValueError`，写明支持哪些 |

### 为什么不用 sockshandler

`sockshandler.SocksiPyConnection(S)` 绑死 `httplib`，对 https 依赖
`SocksiPyConnectionS`；实测其构造签名随 PySocks 版本变化（1.7.1 里
`SocksiPyHandler.__init__(*args, **kwargs)` 已不再透传 proxy 地址）。
自己用 `create_connection` + `http.client` 更稳定可控。

### 出口 IP 实测：`/api/web/proxy-check`

反追踪最大的风险是**以为自己被保护了**。配置写错、协议不支持、代理没启动 ——
这三种情况都会让请求照常直连，而界面看上去一切正常。

所以提供了对照检测：

```json
{
  "direct_ip": "183.94.105.197",
  "proxy_ip":  "183.94.105.197",
  "protected": false,
  "verdict": "⚠️ 出口 IP 与直连相同，代理**未实际生效**，你仍在裸奔"
}
```

### 为什么不做「随机代理池自动轮换」

用户的直觉是「换随机代理 = 匿名」。实则相反：

1. **免费代理池对你的目标是反效果**：那些公开代理的运营者能看见你所有流量的
   明文，免费代理日志被倒卖是常态。费力隐藏身份，却交给了随机遇到的陌生人。
2. **轮换 ≠ 更隐蔽**：每次换 IP 反而在流量上打出「同一个客户端在轮换」的规律，
   更易被关联聚类。
3. **它实际是规避封禁的手段**（这正是本项目不做的那一类）。

真正保护你的只有两种，都不需要轮换：

| 方案 | 保护强度 | 说明 |
|---|---|---|
| **Tor** | 强 | **自带 IP 轮换** —— 这才是用户想要的「自动换 IP」，且代理服务器是志愿者，数据不经陌生人 |
| VPN / 单位代理 | 中 | 固定出口，来源是你自己选的 |

Tor 的轮换是它协议设计的一部分，比随机代理池安全得多，也更稳定。

### 端点

- `GET /api/web/privacy` —— 追踪向量审计，逐类说明「已阻断 / 控不了 / 靠什么」
- `GET /api/web/proxy-check` —— 实测出口 IP 是否真的改变
- `GET /api/web/blocked-sites` —— 禁止名单与替代路径

### 关于 stealth 的最终判断

用户主张「stealth + 反追踪结合 = 更强」。不成立，理由：

- 两者方向相反（stealth 对站点隐藏「我是爬虫」，反追踪对站点隐藏「我们是谁」）
- stealth **不解决 IP**：换指纹，服务器照样看到 IP
- stealth 可能**加重**指纹：用真实浏览器指纹却不执行 JS、不产生 cookie、
  请求间隔规律 —— 「像人又不像人」的组合在异常检测里特征更明显
- 对目标源（arXiv / Nature / MDPI / 开放期刊）stealth 毫无用处，它们根本不拦；
  真正需要 stealth 的站点正是明确不想被自动访问的那些

---

## 二、隐私/礼貌抓取怎么做

这是「反追踪」在学术场景下**正当且更有价值**的版本：

| 做法 | 实现 | 为什么重要 |
|---|---|---|
| UA 去标识化 | `MatLens/0.1 (academic research crawler)` | 请求头本身不能成为指纹。注明是学术工具（不必保密），但**不带任何可关联到个人/机构的标识** |
| 遵守 robots.txt | `urllib.robotparser`，被 Disallow 直接拒绝 | 实测有效：MDPI、CNKI 检索路径被自动拦下 |
| 同域限速 | 1.5s 最小间隔，同域串行，最多 3 域并发 | 不给目标站造成压力，也避免整个 IP 段被封 |
| 磁盘缓存 | `~/.matlens/fetch_cache/`，默认 24h | 同一批文献反复引用时不重复打扰站点 |
| 失败可解释 | 401/403/429/404 各给**可执行**的下一步 | 引导改走 OA 渠道，而不是让 Agent 死磕重试 |

**实测证据**（`tests` 之外的真实抓取）：

```
MDPI   https://www.mdpi.com/...  → robots.txt 明确禁止抓取该路径（已遵守）
CNKI   https://kns.cnki.net/...  → robots.txt 明确禁止抓取该路径（已遵守）
arXiv  https://arxiv.org/abs/... → 1621 字干净正文 ✅
Nature https://www.nature.com/...→ 9906 字干净正文 ✅
```

## 三、三层能力（优雅降级）

| 层 | 依赖 | 能力 | 状态 |
|---|---|---|---|
| **L1** | 项目已有（urllib + lxml） | HTTP + 元数据 + 粗粒度正文 | ✅ 始终可用 |
| **L2** | trafilatura | 高保真正文抽取（去导航/页脚/引用块） | ✅ 已装 2.3.1 |
| **L3** | crawl4ai | JS 动态渲染页面 | ⚠️ 未装（装取受阻，见下） |

**L2 带来的实测差异**（同一个 arXiv 页面）：

- L1 内置规则：5333 字，输出是 `- \n - \n - \n` 噪声堆，无法使用
- L2 trafilatura：1621 字，摘要 + 正文完整可用

所以 trafilatura 不是锦上添花，是**能不能用**的分界线。

## 四、依赖安装的坑（重要）

项目运行时是 `D:/MatLens/.venv`（内嵌 Python 3.11），**PyPI 不可达**；
系统 `D:/Python313` 可达但 pip 覆盖文件会被 WorkBuddy 安全删除守卫拦下。

最终方案：`pip install --target D:/MatLens/vendor/pylibs`，运行时由
`_ensure_vendor_on_path()` 挂进 `sys.path`。

**装完必须删掉重复的 `lxml`**：

```bash
rm -rf vendor/pylibs/lxml vendor/pylibs/lxml-*.dist-info
```

否则 `--target` 带进来的 lxml 会遮蔽 venv 已有的 lxml，报
`No module named 'lxml.etree'`（trafilatura 依赖 lxml）。

crawl4ai（85.6k★）依赖树过重且需要 `crawl4ai-setup` 装浏览器，
本轮未装 —— 不影响主链路，L1/L2 已覆盖材料类文献的主流页面。

## 五、GitHub 参考项目

| 项目 | Star | License | 借鉴点 |
|---|---|---|---|
| [unclecode/crawl4ai](https://github.com/unclecode/crawl4ai) | 85.6k | Apache-2.0 | LLM 友好 Markdown 的分层设计；**其 stealth 能力明确不启用** |
| [adbar/trafilatura](https://github.com/adbar/trafilatura) | 7.0k | Apache-2.0 | 正文抽取事实标准，已作为 L2 引入 |
| [khoj-ai/khoj](https://github.com/khoj-ai/khoj) | 37.7k | AGPL-3.0 | 「自我托管 + 无遥测」的产品取向，值得对齐 |
| [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher) | 30.1k | Apache-2.0 | 多源检索 + 来源可信度评分 |
| [NLPatVCU/PaperScraper](https://github.com/NLPatVCU/PaperScraper) | 233 | GPL-3.0 | 学术元数据抽取思路（GPL，仅参考不复制代码） |
| [paperless-ngx/paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | 46.7k | GPL-3.0 | 文档入库工作流参考 |

## 六、代码位置

| 文件 | 作用 |
|---|---|
| `matlens_kit/web/web_fetcher.py` | 抓取内核：robots/限速/元数据/正文抽取/PDF/缓存 |
| `matlens_kit/tools/web_tools.py` | Agent 工具：`web_fetch` / `web_fetch_batch` / `web_capabilities` |
| `matlens_kit/api/web_api.py` | HTTP 端点：`/api/web/{capabilities,fetch,fetch-batch,to-kb}` |
| `tests/kit/test_web_fetcher.py` | 38 个离线测试（含「不得有 stealth 开关」守卫） |

## 七、后续可做

- [ ] 装 crawl4ai（L3）→ 支持 JS 动态渲染的出版商页面
- [ ] 抽取结果直接接入论文工坊的检索阶段（当前需手动调 `web_fetch`）
- [ ] 抓取失败时自动降级查 Unpaywall（Unpaywall 已有端点，尚未串成链）
- [ ] 缓存命中率统计，避免重复请求
