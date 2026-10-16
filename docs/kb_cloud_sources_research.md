# 云端学术数据源调研（2026-10-15）

这份文档记录 **GitHub 上现成学术 API 聚合项目的横向调研**，用于论证 MatLens 知识库
「云端 API」数据源的取舍。**不要在代码里凭印象加端点**——所有收录都必须有出处。

## 一、GitHub 现成项目对照

| 项目 | Star | 语言 | 学术源 | 对我们的价值 |
|---|---|---|---|---|
| [cyphalle/omnisearch](https://github.com/cyphalle/omnisearch) | 1 | Rust | arXiv / OpenAlex / CrossRef / PubMed（+ 18 个非学术源共 50+） | **架构范本**：并发、每源超时、单源失败不影响整体、URL 去重、partial failure 显式返回 |
| [damionrashford/RivalSearchMCP](https://github.com/damionrashford/RivalSearchMCP) | 132 | Python | OpenAlex / CrossRef / arXiv / PubMed / Europe PMC + **数据集枢纽** Kaggle / HuggingFace / Dataverse / Zenodo | **源清单印证**：与我们已实现的五个源完全重合；新增的「数据集枢纽」维度值得后续接入 |
| [pastchais/academic-paper-mcp-http](https://github.com/pastchais/academic-paper-mcp-http) | — | TypeScript | 13+ 源，含 CORE / Unpaywall / bioRxiv / medRxiv | 补充了 **Unpaywall**（OA 全文定位）与**预印本服务器**两个可用方向 |
| [xingyulu23/Academix](https://github.com/xingyulu23/Academix) | — | Python | OpenAlex / DBLP / CrossRef / Semantic Scholar / arXiv | 源清单与前几项高度重合；DBLP 单源但与材料化学无关 |
| [scipenai/aminer-mcp-server](https://github.com/scipenai/aminer-mcp-server) | 13 | — | **AMiner**（需 `AMINER_API_KEY`） | **中文科研图谱**，支持中文关键词检索，是对中文文献缺口最现实的补充 |
| [ElliotPadfield/unpaywall-mcp](https://github.com/ElliotPadfield/unpaywall-mcp) | 12 | — | Unpaywall | OA 全文链接解析，仅需邮箱 |
| [evoelsewhere/evoflux](https://github.com/evoelsewhere/evoflux) `references/api-cheatsheet.md` | — | Markdown | 学术 API 速查表 | **限流实测参考**：arXiv ~1 req/3s；S2 免 key 易 429；OpenAlex 10 万/天（带 mailto 进 polite 池） |

### 关键结论

1. **免费学术 API 的格局已经收敛**。四个独立项目不约而同选了同一组源，说明不存在
   「漏掉了一个宝藏免费源」的情况。真正的差异只在于要不要接付费源。
2. **「数据集枢纽」是被多数项目忽略的维度**（仅 RivalSearchMCP 纳入）。
   对材料科研而言 Zenodo / HuggingFace 有大量电池/电解质数据集，价值不低于论文，
   列为后续扩展项。
3. **中文文献是公认的缺口**，没有任何一个项目真正解决。AMiner 需要申请 key，
   知网/万方走不通（见下）。

## 二、中文文献：为什么没有端点

这部分必须**如实告知用户**，不能因为「应该有」就伪造一个接口。

| 数据库 | 状态 | 证据 |
|---|---|---|
| **知网 CNKI** | ❌ 无公开 API | 官方 Open API 仅限**签署合作协议**的高校/科研机构/图书馆，需单位资质证明与合作意向书；个人无法自助申请，第三方「代申请 / 共享密钥」属违规。 |
| **万方** | ⚠️ 有官方开放平台但按点计费 | `api.wanfangdata.com.cn`，需申请 token 后配置环境变量 `WANFANG_TOKEN` |
| **维普 / 超星** | ❌ 无可用接口 | 自动化请求返回 412 / 滑动验证 |
| **AMiner** | ⚠️ 需申请 key | 中文科研图谱，支持中文关键词；配置 `AMINER_API_KEY` 后可用 |

**知网检索通道实测记录**（来自 cnki-literature-audit 项目的 field notes）：
`kns.cnki.net/kns8s/search` 直连 302 跳滑块验证；`search.cnki.com.cn` 的 JSON 接口
已废弃（真浏览器内 XHR 也 403）。唯一可行的是首页人工检索。

### 唯一正确的中文文献路径

```
知网/万方 官网人工检索 → 导出 Refworks / EndNote 题录 → 解析 → 导入本地知识库
```

MatLens 知识库页「添加文献」tab 已支持本地文件导入，这条路径**完全可用**。
界面上必须把这条路说清楚，而不是留一个灰色的「知网」按钮。

## 三、我们已实现的源与实测状态

| 源 | 免 key | 实测结果 | 默认勾选 |
|---|---|---|---|
| OpenAlex | ✅ | ✅ 稳定，材料类命中好 | ✅ |
| Crossref | ✅ | ✅ 稳定，DOI 权威，中文期刊收录优于 OpenAlex | ✅ |
| arXiv | ✅ | ✅ 可用（**单次请求高频时易 403，需限流**） | ✅ |
| Semantic Scholar | ✅（可选 key） | ⚠️ **实测几乎必 429**，已加指数退避 | ❌ |
| Europe PMC | ✅ | ✅ 可用，但材料学科覆盖弱 | ❌ |
| PubMed | ✅ | ✅ 可用，但材料方向基本不适用 | ❌ |
| DBLP | ✅ | ❌ **站点已启用反爬验证**（Anubis），对数据中心 IP 返回质询页 | ❌ |
| Unpaywall | 只需邮箱 | ✅ 用于 OA 全文定位（按 DOI 查） | 后续 |
| AMiner | 需 key | 中文图谱 | 后续（配 `AMINER_API_KEY`） |
| 万方 | 需 token | 未配置时不请求，不伪造 | ❌ |

## 四、工程约束（踩过的坑）

1. **总预算机制**。多源并发若各自退避重试，最坏情况能把请求拖到 47s（实测）。
   `search_web()` 设 `TOTAL_BUDGET = 26s`，到点即返回已完成源的结果，
   剩余源标记 timeout——前端绝不能长时间空转。
2. **arXiv 403 是并发限流**，不是封禁。单请求 http/https 均 200。
   已对同源加请求间隔。
3. **摘要为空是常态**，不是 bug。OpenAlex/Crossref 对老文献与付费墙期刊
   普遍返回 null，UI 需如实提示「该源未返回摘要」。
4. **不要伪造端点**。未配置的付费源直接抛可读错误（`未配置 WANFANG_TOKEN`），
   由上层标灰，而不是静默返回空结果让用户以为「搜过了没有」。

## 五、后续可做

- [ ] 接入 **Unpaywall**：按 DOI 解析合法 OA 全文链接（只需邮箱）
- [ ] 接入 **数据集枢纽**：Zenodo / HuggingFace（材料数据集价值高）
- [ ] 接入 **AMiner**：中文文献补缺，需申请 key
- [ ] 接入 **Refworks/EndNote 题录解析**：打通知网人工检索的落地链路
- [ ] 源健康面板：定时自检各源可用性，避免用户点了才发现配额耗尽
