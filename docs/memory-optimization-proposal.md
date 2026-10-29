# MatLens 记忆功能优化建议书

> 版本：v1.0 ｜ 日期：2026-10-29 ｜ 范围：后端记忆架构 + 前端记忆界面 + 论文/文献调研
> 定位：面向材料化学论文写作 Agent 的长期记忆系统设计

---

## 摘要（一页看懂）

**一句话诊断**：MatLens 的记忆层目前是**"能存能取，但看不见、管不住、记不准"**——后端有 8 个 provider 的成熟插件生态，前端却**完全没有记忆本体的界面**；写入靠 LLM 抽取、检索靠单一向量相似度，两者都没有"记忆治理"（遗忘、冲突仲裁、来源溯源）。

**三个最该做的决定**（详见 §5 优先级矩阵）：

| 优先级 | 决策 | 为什么 | 预计投入 |
|---|---|---|---|
| **P0** | 做「记忆中心」前端界面：可见、可改、可删、可溯源 | `mem_api.py` 已有 CRUD，**原型 `design/prototype/` 已有完整实现**，主要是移植 + 补后端契约。记忆是黑箱 = 不可信 = 用户不敢用 | 2–3 天 |
| **P0** | 检索改为**混合检索 + RRF 融合**（向量 + BM25 + 时间衰减 + 图谱邻接） | 论文实证：材料化学语料里 BM25 单独贡献可达 **+0.5 分**（10 分制）；且纯向量检索会漏掉精确材料名/参数名 | 3–5 天 |
| **P1** | 引入**记忆类型学 + 双层架构**（原文层 / 提炼层）+ 冲突仲裁 | 借鉴 A-MEM、Hindsight、Mem^p；解决"同一材料两个矛盾结论"这一科研场景致命问题 | 2–3 周 |

**一个反直觉但重要的结论**：论文 arXiv:2607.16848 用**科学文献语料**（81 + 252 篇论文）实测 8 套记忆系统，发现——**固定检索预算后，复杂架构相对朴素 RAG 的优势在统计上基本消失**（Simple RAG 7.25 vs Theoria 7.19 vs Mem0 6.97，CI 互相覆盖）。也就是说：**不要为了"架构先进"去做大重构**，把钱花在「可见性 + 混合检索 + 冲突仲裁 + 评测」这四件事上，回报率远高于上 GraphRAG。

---

## 目录

1. [现状盘点：MatLens 记忆系统到底有什么](#1-现状盘点matlens-记忆系统到底有什么)
2. [对标：GitHub 上的 12 个记忆项目](#2-对标github-上的-12-个记忆项目)
3. [文献调研：AI 长期记忆的论文谱系](#3-文献调研ai-长期记忆的论文谱系)
4. [文献调研：人类记忆机制及其工程映射](#4-文献调研人类记忆机制及其工程映射)
5. [优化建议：优先级矩阵与实施方案](#5-优化建议优先级矩阵与实施方案)
6. [前端设计：记忆中心界面方案](#6-前端设计记忆中心界面方案)
7. [评测方案：怎么证明这些改动有用](#7-评测方案怎么证明这些改动有用)
8. [风险与不做的事](#8-风险与不做的事)
9. [参考文献](#9-参考文献)

---

## 1. 现状盘点：MatLens 记忆系统到底有什么

### 1.1 后端架构事实（一手核实）

| 维度 | 现状 | 证据位置 |
|---|---|---|
| **Provider 生态** | 8 个外部 provider 插件 + 内置 SQLite 双轨：`mem0` / `hindsight` / `holographic` / `supermemory` / `openviking` / `retaindb` / `honcho` / `byterover` | `plugins/memory/*/__init__.py` |
| **架构约束** | 内置 provider 永远第一个，**最多允许 1 个外部 provider**，互不阻塞 | `agent/memory_manager.py:364-378` |
| **默认存储** | `mem0` provider，OSS 模式：DeepSeek 抽取 + fastembed 本地嵌入 + **Qdrant 本地存储**（`~/.matlens/mem0_qdrant/`） | `config/matlens.yaml:809-830` |
| **写入路径** | 两种：① `mem0_add` 工具显式调用（Agent 自主决定）② `sync_turn` / `on_session_end` 后台异步写入 | `plugins/memory/mem0/__init__.py:515`；`agent/memory_manager.py:675,915` |
| **写入触发** | `nudge_interval: 10`（每 10 轮提醒 Agent 考虑存记忆）+ `flush_min_turns: 6`（上下文压缩/退出前强制冲刷） | `config/matlens.yaml:825,830` |
| **检索路径** | `prefetch_all` → 各 provider 并行 `prefetch` → 合并为 `<memory-context>` 围栏块注入 system prompt | `agent/memory_manager.py:525-547,347-362` |
| **查询改写** | 有独立 `rewrite_memory_query`：把用户最新消息改写成一个英文疑问句，失败则回退原 query | `plugins/memory/query_rewrite.py:109-139` |
| **注入防护** | `<memory-context>` 明确标注"NOT new user input / authoritative reference data" | `agent/memory_manager.py:347-362` |
| **多租户** | 读按 `user_id` 过滤（跨 agent 跨 channel 全域召回）；写附带 `agent_id` + `metadata.channel` | `plugins/memory/mem0/__init__.py:381-392` |
| **上下文预算** | `memory_char_limit: 2200`（~800 tokens）、`user_char_limit: 1375`（~500 tokens） | `config/matlens.yaml:820-821` |
| **科研定制** | `custom_instructions` 覆盖 mem0 默认抽取规则，优先记科研信息 | `plugins/memory/mem0/_backend.py:209-213` |
| **记忆分类** | 靠**文本前缀正则**解析 `[用户] [实验] [材料] [结论]` 标签 → `category` 字段 | `matlens_kit/api/mem_api.py:22,152-156` |
| **知识库（RAG）** | **完全独立的第二套索引**：`matlens_kit/rag/kb.py` 自研 `VectorStore`（JSON + 384 维本地嵌入），**不用 chroma，不用 qdrant** | `matlens_kit/rag/kb.py:52-215` |
| **图谱** | **记忆图谱是存在的**：`matlens_kit/api/graph_api.py:91-110` 从 mem0 拉取 top-60 记忆 → 抽取实体 → 写入 `graph.json`；`agent/learning_graph.py` 是**另一套** skill 关系图（skill 节点 + `related_skills` 无向边） | `matlens_kit/api/graph_api.py:91`；`agent/learning_graph.py:29-177` |
| **全文检索底座** | `matlens_state_search.py` 已有 **FTS5 + trigram + CJK 分词**的成熟全文检索（SQLite FTS5，含 CJK triggers、增量 merge、FTS 重建水位）——P0-B 混合检索可直接复用 | `matlens_state_search.py:1-114` |
| **设计已规划未实现** | `design/frontend-design.md:104-107` 早已规划「右侧上下文面板 📚 记忆 标签页」+「记忆图谱蜘蛛网页（vis-network 力导向，点击节点侧栏显示关联记忆条目，可编辑/删除）」——**需求写好了，三套前端都没实现** | `design/frontend-design.md:104-107` |
| **前端接口** | `matlens_kit/api/mem_api.py` 定义 5 个记忆 CRUD 路由：`GET /`（列表/检索）、`POST /`（新增）、`GET /status`、`PATCH /{id}`、`DELETE /{id}` | `matlens_kit/api/mem_api.py:185-269` |
| **⚠️ 接口冲突** | `mem_api` 的 router 挂在 `matlens_kit/api/server.py:151`；而**生产入口** `matlens_cli/web_server.py` **未挂 mem_api**，自己在 `:13508` 定义了同名 `GET /api/memory` —— 返回的是 **provider 状态**（active/providers/builtin_files），不是记忆列表。**两个 `/api/memory` 语义完全不同** | `matlens_cli/web_server.py:13508-13533`；`matlens_kit/api/server.py:151` |

### 1.2 十个诊断结论

**① 前端有记忆的"配置界面"，没有记忆的"本体界面"——但原型里已经写好了**

三套前端（`web/` React、`apps/desktop/` Electron、`design/prototype/` 原生 JS）中，**只有 `design/prototype/` 有完整的记忆管理实现**：
- `design/prototype/app.js:2823-2945`：`loadMemories()` / `renderMemCats()` / `renderMemories()`，已对接 `GET /api/memory`、`DELETE /api/memory/{id}`、`POST /api/memory`
- `design/prototype/index.html:2123-2150`：记忆管理页（搜索框 `#mem-search`、添加记忆弹窗、类别筛选 `#mem-count`）
- `design/prototype/index.html:1799`：右侧栏「记忆」标签页（"Agent 记住的偏好与事实"）
- `design/prototype/index.html:1629`：左栏「记忆图谱」入口
- `design/prototype/index.html:1419`：记忆召回提示条样式
- `design/prototype/index.html:1719-1721`：命令面板「翻阅记忆 —— Agent 记住了什么」

**`web/src/` 与 `apps/desktop/` 完全没有这些**。`web/src/lib/api.ts:1170` 只定义了 `getMemory()`，只在 `SystemPage.tsx:259` 用于状态条和 `resetMemory`。

> **这是本次调研对工程量判断影响最大的发现**：P0-A 不是"从零设计"，而是**把原型已有实现移植进 `web/src/`，再补齐后端契约**。这直接省掉一个完整的设计+实现周期。

**⚠️ 但原型实现本身与后端契约对不上**：
- 原型 `app.js:2827` 请求 `/api/memory`（不带 `q` 时取全量），而生产后端 `matlens_cli/web_server.py:13508` 的同名路由返回的是 **provider 状态**，不是记忆列表
- 原型用 `GET /api/memory?q=...` 做搜索，但 `mem_api.py:194` 在 `q` 为空时会用宽泛词拉一批，并非真正的全量列表
- 原型的删除走 `DELETE /api/memory/{id}`，而生产后端**未挂 mem_api router**（见下）

**② 后端接口冲突：两个 `/api/memory` 语义完全不同**

`mem_api.py` 的 router 挂在 `matlens_kit/api/server.py:151`；而**生产入口** `matlens_cli/web_server.py` **未挂 mem_api**，自己在 `:13508` 定义了同名 `GET /api/memory` —— 返回 `{active, providers, builtin_files}`（provider 状态），不是记忆条目。

→ **这是 P0-A 的第一道硬骨头**：不是"纯前端增量"，必须先解决 router 挂载 + 路径统一。

**③ 检索是单一向量相似度，没有混合检索**

`OSSBackend.search` 只有一句 `self._memory.search(query, filters, top_k)`（`plugins/memory/mem0/_backend.py:280-282`）。`rerank` 参数在 OSS 模式下被透传给 mem0 但**实际不生效**（`plugins/memory/mem0/__init__.py` 只在 platform 模式下标注 "Rerank is available on search"）。

这在材料化学场景是硬伤：用户问"我之前用的 NCM811 掺杂量是多少"，"NCM811"是精确字符串，稠密嵌入会把它和"层状氧化物"混淆，而 BM25 能精确定位。

**③ 没有遗忘机制，记忆只增不减**

全局搜 `decay` / `forget` / `evict` / `ttl` / `consolidat`：`mem_trim.py` 只处理 **prompt 层面的 token 裁剪**，不是记忆条目生命周期。全项目**没有**对已存记忆条目的时间衰减、合并、去重、矛盾仲裁。

对照人类记忆：Ebbinghaus 遗忘曲线表明不复习的记忆 24 小时内损失 70%。Agent 记忆同理——三个月前的实验参数偏好如果没失效，会持续污染检索。

**④ 记忆分类靠正则文本前缀，不是结构化字段**

`matlens_kit/api/mem_api.py:152-156` 用 `^\s*\[([^\]]+)\]\s*` 从记忆正文里"抠"出类别。这意味着：类别不是可查询的数据库字段，无法按类别做过滤聚合；一旦 LLM 抽取时不加前缀，分类就退化为 `"其他"`。

**⑤ 前端拿不到"来源"和"时间"**

`mem_api.py:159-168` 的 `_normalize()` 虽然吐了 `created_at` 和 `metadata`，但上游 `mem_api` 的 `mem0_search` 返回只保留 `id/memory/score` 三个字段（`plugins/memory/mem0/__init__.py:583-584`），**`created_at` 和 `metadata` 根本不会传下来**——它们在 provider 层就被丢掉了。

→ 前端即使接上列表，也**拿不到时间戳、拿不到来源**。溯源字段缺失是 P0-E 的核心内容，且**修复点在 provider 层而非 API 层**。

**⑥ 记忆与知识库是两套割裂的索引，会产生"双份事实"**

记忆走 mem0 → Qdrant；知识库走 `kb.py` 自研 JSON 向量存储 + 384 维本地嵌入。同一篇论文可能既进了知识库又进了记忆，两边独立嵌入、独立检索、**没有交叉引用**。用户问"我之前存的那篇 SOFC 电解质论文在哪"时，两边都可能命中也可能都不命中，且无法解释命中的是哪一个。

**⑦ 记忆图谱只在后端，前端没有**

`graph_api.py:91-110` 确实从 mem0 拉记忆建了实体图谱（`graph.json`），`design/frontend-design.md:109-112` 也规划了 vis-network 力导向的记忆图谱交互（点击节点 → 侧栏显示关联记忆条目，可编辑/删除）。但**三套前端都没有实现这个视图**——图谱数据躺在磁盘上没人看。

**⑧ 全文检索底座已存在，但没用在记忆上**

`matlens_state_search.py` 实现了 FTS5 + trigram + CJK 分词的全文检索（含 CJK triggers、增量 merge、重建水位管理），工程质量不低。但记忆检索走的是纯向量路径。**这是 P0-B 最省力的切入点——底座现成，只是没接。**

**⑨ 记忆条数统计是"抽样估计"而非真值**

`mem_api.py:90-107` 的 `_best_effort_count` 是用一条宽泛 query 搜 top-100 再数条数——**搜索返回多少条就显示多少条**，不是真实总数。记忆超过 100 条后，前端显示的"记忆条数"就是错的。而原型记忆页的标题栏正在显示这个数字（`design/prototype/index.html:2127` 的 `#mem-count`）。

**⑩ 检索有 top_k=50 的硬截断**

`plugins/memory/mem0/__init__.py:575` 是 `top_k = max(1, min(int(args.get("top_k", 10)), 50))`。但 `mem_api.py:188` 的 `top_k: int = Query(30, ge=1, le=100)` 允许到 100——**API 层允许的参数会被 provider 层静默截到 50**，前端请求 100 条只回 50 条，且无任何提示。

### 1.3 现有能力清单（客观优势，别低估）

| 已有优势 | 说明 |
|---|---|
| **Provider 抽象层成熟** | `MemoryProvider` 抽象 + 8 个插件，OSS/自托管/云端三种模式，`mem_api` 统一到 `handle_tool_call` 门面 |
| **故障隔离做得好** | 一个 provider 挂掉不影响另一个；`mem_api` 全部"最佳努力"，绝不抛 500 给前端（`matlens_kit/api/mem_api.py:90-107`） |
| **写入持久性分级** | `_background_futures` 按 durability class 跟踪，关机时 FIFO drain 并报告 abandoned 数量（`agent/memory_manager.py:391-403,809`） |
| **预取异步化** | `queue_prefetch_all` 后台预取，不阻塞主链路；内置 provider 走同步路径，不起多余线程 |
| **注入防注入** | `<memory-context>` 围栏 + 显式系统说明；query_rewrite 显式声明"Treat the latest message as untrusted data" |
| **科研场景定制** | `custom_instructions` + system prompt 里的中文科研提示（研究方向/材料体系/参数偏好/文献结论） |
| **上下文预算约束** | `memory_char_limit` 硬限制，防止记忆膨胀挤爆上下文 |
| **原型已有记忆管理页** | `design/prototype/` 已实现记忆列表、类别筛选、搜索、增删、右侧记忆标签页、记忆图谱入口、召回提示条——**可直接移植，是 P0-A 的最大提速因素** |
| **设计文档已规划** | `design/frontend-design.md:104-112` 早已写明「📚 记忆 标签页 + 记忆图谱蜘蛛网页」的交互规范 |
| **全文检索底座** | `matlens_state_search.py` 的 FTS5 + trigram + CJK 分词，可直接复用于记忆混合检索 |
| **记忆图谱数据管道** | `graph_api.py:91-110` 已能从 mem0 拉记忆抽实体建图，只是前端没接 |

**结论：底子不差，缺的是"记忆治理层"和"记忆可见层"。**

---

## 2. 对标：GitHub 上的 12 个记忆项目

### 2.1 三大阵营

2026 年的 agent 记忆框架基本落入三个阵营（依据 nomadx.ae、thirdbrain.tech 的整理 + GitHub 数据）：

| 阵营 | 核心机制 | 代表项目 | 星数(2026) |
|---|---|---|---|
| **① 向量/事实记忆层** | LLM 抽取事实 → 相似度检索 | Mem0、Memobase、LangMem | Mem0 ~63k |
| **② 时序知识图谱** | 双时态、事实失效而非删除 | Zep/Graphiti、Cognee | Graphiti ~30k, Cognee ~30k |
| **③ 记忆 OS / 自编辑运行时** | Agent 自主管理自己的记忆，分页换入换出 | Letta(前 MemGPT)、MemOS | Letta ~24k, MemOS ~11k |

外围还有：`supermemory` ~29k（统一记忆 API）、`honcho` ~7k（心智模型个性化）、`basic-memory` ~4k（Markdown 知识图谱 + MCP）、`A-MEM`（Zettelkasten 动态链接）、`MemPalace`（2026-04 爆红，两天 23k 星）。

### 2.2 与 MatLens 最相关的 6 个项目

#### ① Mem0 —— MatLens 已经接了，但要升级用法

**架构**（arXiv:2504.19413）：两阶段流水线
- **提取**：`(会话摘要 S, 最近 m=10 条消息, 新消息对)` → LLM 抽取候选事实 Ω
- **更新**：对每条候选，向量检索 top-s=10 相似记忆，LLM 通过 function call 选择四操作之一：
  - `ADD` 无等价记忆 → 新建
  - `UPDATE` 有互补信息 → 增强
  - `DELETE` 新信息矛盾 → **删除旧记忆**
  - `NOOP` 无新增信息 → 不动

**Mem0 官方 2026 年的新东西（MatLens 当前未用）**：
- **Memory Decay**：不是淘汰，是**检索时重排降权**。最近访问的记忆得分最高 1.5×，长期未用的降到 0.3×。这是 Bjork "存储强度 vs 提取强度"区分的工程化——**事实永不删除，只是变难召回**。
- **Dream 记忆整合**（Pro 版）：离线批量 consolidation
- 三层生命周期：conversation（单次响应）/ session（分钟到小时）/ user & org（长生命周期）

**给 MatLens 的启示**：MatLens 目前用的是 mem0 的"抽取-存储"部分，但**没有暴露 ADD/UPDATE/DELETE/NOOP 的决策给用户看**。科研场景里"新实验数据推翻了旧结论"必须走 `UPDATE` 而不是并存两条矛盾记忆——mem0 底层支持，MatLens 需要在 UI 层把它显性化。

#### ② Hindsight（Vectorize + Virginia Tech）—— **最值得 MatLens 借鉴**

**四网络认识论架构**（把"事实"和"信念"彻底分开）：

| 网络 | 存什么 | 例子 |
|---|---|---|
| **World** | 客观事实，独立于 AI 视角 | "Alice 在 Google 工作" |
| **Experience** | AI 自身的第一人称经历 | "我上周二向 Alice 推荐了优胜美地" |
| **Observation** | 从零散事实合成的实体侧写 | "Alice 是专注机器学习的 Google 工程师" |
| **Opinion** | 主观信念 + 置信度 + 时间戳 | "Python 是数据科学最好的语言（0.85）" |

**三个核心操作**：
- `Retain`：**叙事性事实提取**——不是切碎成"Bob 建议叫 Summer Vibes / Alice 不喜欢"，而是压成一个完整叙事："Alice 和 Bob 讨论播放列表命名，Bob 建议 X，Alice 想要更独特的，最终达成一致选了 Y"。**这个思路对论文写作极其贴切**：一条记忆应该是一个完整的科研叙事单元，而不是碎片。
- `Recall`：**TEMPR** 四路并行检索 → RRF 融合 → cross-encoder 重排
  - semantic（语义）
  - BM25 keyword（关键词）
  - graph activation（图激活）
  - temporal-graph parsing（时序图解析）
- `Reflect`：**CARA**，按优先级处理记忆（opinions/observations 先于 raw facts），并把新信念写回 opinion network，闭环。

**成绩**：20B 开源模型在 LongMemEval-S 上 **83.6%**，超过全上下文 GPT-4o 的 **60.2%**；BEAM 10M-token 基准 **64.1%** vs 次名 40.6%。

**MatLens 的 Hindsight 插件已经存在**（`plugins/memory/hindsight/`），但——**这是本次调研最重要的发现之一**——arXiv:2607.16848 的科学文献评测显示：**Hindsight 在论文语料上表现不佳**（Paim 30K 预算下 6.53 分，显著低于 Simple RAG 的 7.25，CI [+0.18, +1.30] 排除 0）。论文归因于三点：① Hindsight 设计预期是 **conversation exchanges**，不是 20K-token 的整篇论文；② 300KB ingest cap **直接拒收了三篇论文**；③ server-side recall cap 固定返回 ~19K 字符，**对预算参数无响应**。

> **教训**：Mem0 的 `add(messages=[...])` 语义与 Hindsight 的"一次一整篇论文"语义不能混为一谈。MatLens 如果要用 Hindsight provider 处理文献记忆，**必须先解决整篇论文的 ingest 单位问题**。

#### ③ A-MEM（Rutgers）—— 记忆演化的理论标杆

**核心**：Zettelkasten（卡片盒笔记法）→ 原子化 + 动态链接 + **记忆演化**

- 新记忆进来 → LLM 生成结构化 note（contextual description + keywords + tags + embedding）
- 分析历史记忆库找相关连接 → 建立 links
- **记忆演化**：新记忆的融入**触发对既有记忆 context/属性的更新**——整个记忆网络持续精化

**成绩**：DialSim F1 **3.45**（vs LoCoMo 2.55，vs MemGPT 1.18）；多跳推理较 GPT baseline 翻倍；每次记忆操作 token 减少 85–93%（约 1200 tokens）；1M 条目检索 3.70 μs。

**MatLens 的相关性**：`agent/learning_graph.py` 已有图谱能力，A-MEM 的"记忆链接 + 记忆演化"是它自然的下一步。而且 A-MEM 强调的 **"新记忆触发旧记忆更新"** 正好对应科研场景："这批新 XPS 数据推翻了之前的结论"。

#### ④ MemPalace —— 本地优先分层，与 MatLens 部署环境最像

**五层空间架构**：

```
Wings（人/项目）→ Halls（同 wing 内房间关联）
                  → Rooms（主题/文件/实体聚类）
                  → Tunnels（跨 wing 房间连接）
                  → Drawers（逐字原文）
```

- **Drawer 保留逐字原文**（"verbatim always"）——不摘要、不改写，事实底座不被 LLM 摘要损失污染
- **Closet**：AAAK 压缩表示层（30x 无损压缩方言），用于检索增强
- **Room**：embedding centroid 吸附 + LLM 提议聚类，有 consent gate（未经授权不外传数据）
- **Hall/Tunnel**：路径感知、文件感知的实体共现图（`src/models/user.py` 与 `tests/models/user.py` 不会因同名合并）

**检索两遍**：① 语义/混合召回 → ② 类别感知 bonus 增强（keyword boosting / temporal-proximity boosting / preference-pattern extraction）→ ③ 可选 LLM rerank top-20

**成绩（本地零 API）**：LongMemEval R@5 **96.6%**（raw semantic，无需任何 key/LLM）；hybrid v4 held-out **98.4%**；LoCoMo session R@10 60.3%（hybrid v5 88.9%）；MemBench R@5 80.3%。

**它的自我批评值得抄**：README 明确拒绝把最后 0.6%（需人工检查错例）当 headline，标注为 "teaching to the test"；也拒绝与 Mem0/Mastra/Hindsight 做并排比较（"不是诚实的比较"）。**这种评测诚实度是 MatLens 建立自身可信度时该学的。**

**MatLens 的相关性最高**：MatLens 定位是**本地优先的科研 Agent**（DeepSeek + 本地 qdrant + 阿里云自部署），MemPalace 的架构假设与 MatLens 几乎同构。**"原文层 + 提炼层"的双层结构应该被 MatLens 采纳。**

#### ⑤ Zep / Graphiti —— 双时态知识图谱

**双时态模型**：每个事实带**事件时间（event time）**和**系统时间（system time）**，矛盾时**标记失效而非删除**，因此仍可回答"在 X 之前 Y 是什么"。

- 节点：实体（类型 + embedding + 创建时间）
- 边：关系三元组 `(Alice, lives_in, San_Francisco)`
- 冲突时 LLM resolver 把旧关系标记为 invalid，同时保留历史 → 支持时序查询
- 检索：实体中心搜索（找匹配节点 → 展开边）+ 三元组文本语义搜索
- 后端：Neo4j / FalkorDB / Neptune（Kuzu 已弃用）

**MatLens 的相关性**：科研场景里"我之前用的是 A 方案，现在改成 B 了"必须有版本关系。MatLens 的 `learning_graph.py` 是图，但**没有双时态语义**。

#### ⑥ MemOS —— 记忆的"类型学操作系统"

三类型统一：**plaintext**（明文）/ **activation**（激活态）/ **parametric**（参数化）
基本单元 **MemCube**：内容 + 元数据（**provenance 来源 + versioning 版本**），可组合、迁移、融合。

> **MemCube 的 provenance + versioning 字段是 MatLens 最该立刻补的**——科研记忆没有来源溯源就没有可信度。

### 2.3 GitHub 项目能力对照表

| 项目 | 存储 | 检索 | 遗忘/衰减 | 冲突仲裁 | 来源溯源 | 图谱 | 本地化 | MatLens 现状 |
|---|---|---|---|---|---|---|---|---|
| Mem0 | 向量(+可选图) | 语义+BM25+实体 | ✅ Decay 降权 | ✅ 4操作 | 部分 | ⚪ Mem0g | ✅ | 已接，**未用 Decay** |
| Hindsight | 四网络图 | 4路并行+RRF+rerank | ⚪ | ✅ CARA | ✅ | ✅ 核心 | ✅ | 已接，**论文场景不适配** |
| A-MEM | 动态链接笔记 | 语义+链接 | ⚪ | ✅ 记忆演化 | ✅ | ✅ | ✅ | 未接 |
| Graphiti | 双时态图 | 混合+图 | ✅ 失效非删除 | ✅ | ✅ | ✅ 核心 | ⚠️ 需 Neo4j | 未接 |
| MemPalace | Chroma+SQLite | 语义+类别感知 bonus | ⚪ 遍历计分 | ⚪ | ✅ 原文 | ✅ Hall/Tunnel | ✅ 零 API | 未接 |
| MemOS | MemCube | 调度 | ✅ | ✅ | ✅ 版本 | ⚪ | ⚪ | 未接 |
| Letta | 块级可编辑 | 分页 | ✅ OS 式 | ⚪ 手工 | ⚪ | ⚪ | ✅ | 未接 |
| Cognee | 类型化 KG | ECL | ✅ improve/forget | ✅ | ⚪ | ✅ | ✅ | 未接 |
| **MatLens 现状** | **mem0+Qdrant / kb.py 自研 JSON 双轨** | **纯向量** | **❌ 无** | **⚠️ mem0 底层有，未暴露** | **⚠️ 部分（channel）** | **⚠️ learning_graph 无时序** | **✅** | — |

---

## 3. 文献调研：AI 长期记忆的论文谱系

### 3.1 综述与分类学（先读这几篇建立坐标系）

| 论文 | arXiv | 核心贡献 | 对 MatLens 的用法 |
|---|---|---|---|
| **A Survey of Agent Memory in the Second Half** | 2602.06052 (TMLR, v4 2026-08) | 60+ 作者。三轴分类：**substrate**（parametric / external）/ **cognitive mechanism**（sensory, working, episodic, semantic, procedural）/ **subject**（user-centric / agent-centric）。另覆盖 memory operations 的 learning policies 与评测基准 | **建记忆类型学体系的骨架**。三轴分类直接可作为 MatLens 记忆 schema 的设计依据 |
| **Memory in the Age of AI Agents** | 2512.13564 (2025-12) | 47 作者。三轴：**Forms**（token-level / parametric / latent）/ **Functions**（factual / experiential / working）/ **Dynamics**（formation / evolution / retrieval） | **指出行业最大缺口 = procedural memory**（"怎么做"而非"是什么/发生过什么"）。生产工具几乎为零 |
| **From Human Memory to AI Memory** | 2504.15965 (Huawei Noah's Ark) | 三维分类：**Object**（personal vs system）/ **Form**（parametric vs non-parametric）/ **Time**（short vs long）。3D-8Q 体系 | 提供"人类记忆 ↔ AI 工程实现"的对照表，是 §4 的桥梁 |
| **A Survey on the Memory Mechanism of LLM-based Agents** | 2404.13501 | 操作中心视角：**write / consolidate / read** | 简洁实用的三段式检查表，适合作为 MatLens 自检清单 |
| **A Survey on the Security of LTM in LLM Agents** | 2604.16548 | 从神经科学论证"记忆即安全问题"：memory 不是档案而是重构（reconstruction）；列出攻击面 | **安全章节必读**。MatLens 有本地记忆 + 网页导入，注入面真实存在 |

### 3.2 架构类论文（按机制分）

| 论文 | arXiv | 机制 | 关键数据 | MatLens 借鉴点 |
|---|---|---|---|---|
| **Mem0** | 2504.19413 | 提取-对比-决策两阶段，ADD/UPDATE/DELETE/NOOP | LoCoMo 优于全上下文，token 减 91% | 冲突仲裁的**语义基础** |
| **MemGPT / Letta** | 2310.08560 | OS 隐喻：core memory（上下文）+ archival memory（向量）+ 自主换页 | — | 记忆预算与换入换出 |
| **A-MEM** | 2502.12110 | Zettelkasten 原子化 + 动态链接 + 记忆演化 | DialSim F1 3.45；token −85~93% | **最贴合 MatLens 的下一代记忆模型** |
| **MemOS** | 2505.22101 / 2507.03724 | 三类记忆统一 + MemCube（provenance + versioning） | — | **provenance/versioning 字段设计** |
| **Mem^p** | 2508.06433 | 程序性记忆 = "从轨迹中蒸馏出的可复用教训" | **ALFWorld：42.14% → 77.86%（+35pp），步数 −37%**；跨模型迁移（GPT-4o 提取的教训给 Qwen2.5-14B +5pp） | **科研 SOP 记忆的直接模板**："当 X 出现时，先查 A，再查 B" |
| **MemMachine** | 2604.04853 | 事实真值衰减的周期性校验；矛盾时和解而非覆盖 | — | 过期实验数据/已废弃方案的清理 |
| **PRIME** | 2604.07645 | 无梯度的工作记忆演化：成功策略/失败模式/用户偏好三区 | — | 失败教训沉淀 |
| **HippoRAG / HippoRAG 2** | 2405.14831 / 2502.14802 | 类海马体：PPR 在开放 KG 上做单步多跳 | 多跳 QA +20%，成本比迭代检索低 10–30× | **多跳检索**，科研问题常需跨文献 |
| **GraphRAG** | 2404.16130 | 实体图 + Leiden 社区摘要 + map-reduce | 全局查询显著优于标准 RAG；**但只支持批量重建** | 全局综述型查询；更新成本高 |
| **LightRAG** | 2410.05779 | 双层（关键词+图）检索 + **增量更新** | token 成本低 10–100×，准确率持平或更优 | **比 GraphRAG 更适合频繁更新的语料** |
| **RAPTOR** | 2401.18059 | 递归抽象树，多分辨率检索 | 多步阅读理解 +20pp | 分层摘要，paper workbench 场景适配 |
| **Hindsight** | (Vectorize) | 四网络 + TEMPR(4路RRF) + CARA | LongMemEval-S 83.6% vs GPT-4o 全上下文 60.2%；BEAM 10M **64.1% vs 40.6%** | 混合检索模板 + 事实/信念分离 |

### 3.3 评测类论文（**对 MatLens 最直接可用**）

#### ★ arXiv:2607.16848 —《Beyond Memory Leaderboards: Evaluating Scientific Memory as Budgeted Context Restoration》

**这是本次调研与 MatLens 定位最贴合的一篇。** 它用**科学论文语料**（Paim：81 篇 / 1.10M words / 2.15M tokens / 66 题；PTr：252 篇 / 98 题）对比 8 套记忆系统。

**被测系统与原生每次查询返回量**：

| 系统 | 原生字符/查询 | 30K 预算得分 |
|---|---|---|
| Graphiti | **2,552,000** | **5.27**（KG-only） |
| Direct Read | 1,968,000 | （oracle 锚点） |
| Cognee | 282,000 | 5.28 |
| Theoria | 28,857 | 7.19 |
| Simple RAG | 21,000 | **7.25** |
| Hindsight | 19,078 | 6.53 |
| Mem0 | 6,222 | 6.97 |
| Base model（无检索） | 0 | 2.64 |

**五条对 MatLens 极其重要的结论**：

1. **Graphiti 的领先完全由上下文体量造成**——原生 8.04 分（最高），一旦固定预算并关闭 episode 模式，掉到 5.27（垫底）。**"最好的记忆架构"可能只是"给了 synthesizer 最多原文"的那个。**

2. **固定预算后，顶部架构差异在统计上消失**（Paim 30K，paired bootstrap 10,000 次）：
   - Simple RAG − Theoria = +0.01，CI [−0.52, +0.53] → 平局
   - Theoria − Mem0 = +0.22，CI [−0.28, +0.74] → 平局
   - Simple RAG − Mem0 = +0.28，CI [−0.18, +0.76] → 平局
   - 但 Simple RAG − Hindsight = +0.72，CI [+0.18, +1.30] → **显著**
   - Simple RAG − Graphiti(KG-only) = +1.98，CI [+1.16, +2.84] → **显著**

3. **BM25 的价值由语料词法结构决定**（不是通用小优化）：
   - PTr（模型名/kernel 名/超参数等稀有字面形式密集）：B≈50K 时 Simple RAG +0.50、Mem0 +0.29、Theoria +0.25，**三个 hybrid 最终收敛到 9.21–9.24，差距 0.03，统计不可区分**
   - Paim（通用科研语料）：收益小且不稳定，Theoria 在 50K 甚至 −0.26
   - **具体案例**：dense 检索找到 FSA 段落但漏掉精确字符串 "Kimi Linear 6× at 11M" → 5.0 分；加 BM25 后 → 10.0 分

4. **更多上下文在平均层面有益，但单个问题可能变差**（PQ44：10K → 9.25，30K → 9.5，50K → **4.5**，因为 50K 时检索到相邻论文并把别人的阶段当成了 HaluMem 的阶段）

5. **LLM judge 的分辨率约 1 分**：112 个盲测人工投票中，分差 0–2 时与人工胜者一致率仅 50%（11/22），2–4 时 90%，≥4 时 100%。**结论：不应把 10 分制内 1–2 分以内的差异当作真实排名差异。**

**该论文建议的科学记忆评测 harness 十项要求**（MatLens 应逐条对照建评测）：
1. 分离 native 与 budget-targeted 两条轨道
2. 显式记录摄取协议（摄取单位大小、是否重叠分块、是否保留 section、是否保留原文、摄取成本、被拒文档）
3. 固定或显式区分答案合成方式（共享同一个 synthesizer）
4. 同时控制 retrieval budget 与 modality（dense / sparse / hybrid + RRF + 各模态 top_k）
5. 全文语料 + 可审计 rubric（每题拆 must-have facts，指向具体 span）
6. 同时报告 L1/L2/L3 分层结果（**L1 已饱和**，综合均值会掩盖差异）
7. 配对统计检验（paired bootstrap，10,000 次，报 mean difference + 95% CI）
8. 校准 judge（第二 judge + 人工盲测 + tie tolerance）
9. 报告可复现工件
10. oracle 与污染探针单独处理（base model 既是性能下限也是参数污染探针）

#### 其他评测基准

| 基准 | 测什么 | 规模 | 关键发现 |
|---|---|---|---|
| **LoCoMo** (ACL 2024) | 多会话对话召回：单跳/多跳/时序/开放域/对抗 | 数据集 50 conv / 7,512 Q；**厂商实际跑的是 ~10 conv / ~1,986 Q 子集** | 全上下文基线 ~73% 常常**打败**记忆系统 ~67% |
| **LongMemEval** (ICLR 2025) | 5 种能力：信息提取 / 多会话推理 / 时序 / **知识更新** / **弃权** | 500 题 / 7 类 | 商用助手在持续交互中退化 ~30% |
| **BEAM** (arXiv:2510.27246, 2025 预印本) | 10 种能力，含**矛盾消解**与**事件排序** | 100 conv / 2,000 Q / 最高 10M token | **1M 上下文模型照样吃力——更大窗口不是解法** |
| **MemoryAgentBench** (2507.05257) | 4 项：精确检索 / **测试时学习** / 长程理解 / **冲突消解与选择性遗忘** | 增量多轮，~100K–1.44M token | "所有方法都无法掌握全部四项" |
| **MemoryArena** (2602.16313) | **主动记忆 vs 被动记忆**：记忆是否真的改变了决策 | 766 个互相依赖的多会话 agent 任务 | **LoCoMo 近饱和的系统在此掉到 40–60%** |
| **STATE-Bench** (Microsoft, 2026-05) | 状态追踪：有经验后是否在有状态任务上变好 | 真实企业级有状态任务 | 相对中立（微软不卖记忆产品） |
| **HaluMem** | **记忆形成阶段的幻觉** | — | **写入时 LLM 编造的事实会永久留在记忆里** |
| **Agent Memory Benchmark** (2602.19320) | 形式化批评：接近饱和的基准衡量的是相似度而非任务效用 | — | — |

**MatLens 的处境判断**：
- 学术记忆类基准（LongMemEval / LoCoMo）只测"能从聊天里回忆事实" → 对 MatLens **价值有限**（MatLens 不是陪聊助手）
- **真正对口的是 BEAM（矛盾消解/事件排序）、MemoryAgentBench（选择性遗忘/冲突消解）、HaluMem（写入幻觉）**——因为 MatLens 的核心价值主张是"帮我写论文别记错我的实验数据"
- **MemoryArena 最值得警惕**：MatLens 若只做"检索注入"，不做"记忆改变决策"，在真实科研流程里价值存疑

#### 安全文献（MatLens 有本地记忆 + 网页导入，必须看）

| 论文 | arXiv | 内容 |
|---|---|---|
| A Survey on the Security of LTM in LLM Agents | 2604.16548 | 记忆即攻击面；memory 是重构不是存档；恶意信息可随每次检索被再次激活 |
| 无需攻击者（cross-user contamination） | 2604.01350 | **正常使用下跨用户污染率高达 57–71%** |
| 记忆投毒攻击 | 2601.05504 | 投毒攻击成功率 6–38% |
| 持续学习与记忆的稳定-可塑性困境 | 2604.27003 | 新旧记忆争夺检索槽位；简单任务原始轨迹损害困难任务（**前向迁移 −9.5%**） |

**MatLens 的安全敞口**：`mem_api` 的 `POST /api/memory` 可直接写入任意文本；`kb_api` 有 `/sources/oa`、`/web-import`、`/web-search`。如果记忆可被网页内容污染 + 检索时注入，就是一条完整的注入链。MatLens 已有 `<memory-context>` 围栏和 query_rewrite 的"untrusted data"声明，但**记忆条目本身没有来源标记**。

---

## 4. 文献调研：人类记忆机制及其工程映射

这一章回答一个问题：**人脑的记忆是怎么工作的，哪些机制值得 Agent 记忆借鉴？**

### 4.1 基础架构：多重存储系统

| 系统 | 容量 | 持续 | 存取 | 工程映射 |
|---|---|---|---|---|
| **感觉记忆** | 极短 | 毫秒–秒 | 感觉登记 | 输入缓冲、原始转写 |
| **工作记忆** | 7±2 组块 | 秒–分钟 | 复述、组块、干扰抑制 | **上下文窗口**（MatLens 的 `memory_char_limit` 就在这层） |
| **长期记忆** | 近乎无限 | 持久 | 编码—存储—提取 | 外部记忆库（MatLens 的主战场） |

**组块（chunking）**：Miller 的 7±2 是"组块数量"而非"信息量"。工作记忆容量有限，**组块策略决定了什么能被存下来**。MatLens 的 KB 分块在 `_split_text`（`matlens_kit/rag/kb.py:277`）有实现，但**记忆条目（mem0_add）没有组块策略**——一条记忆多大合适，无规范。

**长时程记忆三分**（Squire 等）：
- **陈述性记忆**（可用语言表述）
  - **情景记忆**：具体时间地点的事件（"上周三的 XRD 结果"）
  - **语义记忆**：脱离情境的事实（"NCM811 在 800°C 下的离子电导率是 3.2×10⁻³ S/cm"）
- **非陈述性记忆**（内隐）
  - **程序性记忆**：技能与习惯（"怎么写一篇合格的 SOFC 论文"）

**MatLens 的类型学落点**：`[用户] [实验] [材料] [结论]` 这套标签**混合了认知维度**——`[用户]` 是 subject（主体），`[实验]`/`[材料]`/`[结论]` 混了 episodic（实验过程）与 semantic（材料性质）。**建议重构为两维**：
- **subject**（谁/谁的）：user / project / agent
- **function**（认知功能）：factual（语义）/ episodic（情景）/ procedural（程序）/ working（工作）

这样才与 §3.1 的三轴分类对齐，也才能做"按功能检索"。

### 4.2 遗忘机制

#### 艾宾浩斯遗忘曲线

1885 年，无意义音节实验：遗忘在最初几小时最快，之后趋缓。无复习情况下，约 1 小时损失 50%，24 小时损失约 70%。

**两种竞争理论**：
- **衰退理论（decay）**：记忆痕迹随时间被动减弱
- **干扰理论（interference）**：记忆之间互相竞争
  - **前向干扰**（proactive）：旧知识阻碍新学习
  - **倒向干扰**（retroactive）：新学习覆盖旧记忆

> **对 MatLens 的直接启示**：MatLens 的记忆只有**新增 + 更新 + 删除（手动）**，没有任何自动遗忘。**衰退与干扰是两种不同的问题，需要两种不同机制**：
> - 衰退 → **时间衰减降权**（Mem0 Memory Decay 模式：未访问记忆检索得分降至 0.3×，事实不删，只是变难召回）
> - 干扰 → **矛盾仲裁**（新事实与旧事实冲突时，不是两条并存，而是 UPDATE 替换）

**MatLens 目前的"更新"是用户手动 PATCH**。科研场景下这是负担：用户不会记得去改三个月前的记忆。

#### 记忆的干扰与"猫"。**"Spaced effect"（间隔效应）与"Testing effect"（提取练习效应）**

- **间隔效应**：分散学习 > 集中学习（即使集中学习短期感觉更好）。lag effect：间隔太短（<24h）和太长都劣于中等间隔。
- **提取练习效应**（Roediger & Karpicke 2006）：**主动提取比重复阅读更能巩固记忆**。单次小测比重读同一内容在一周后保留率约高一倍。
- **生成效应**：主动产出一个答案（哪怕一开始错）比读答案记得更牢。
- **合意困难（desirable difficulty）**：当下感觉更难的检索练习，事后长期保留更强。
- **自我参照效应**：与自身相关的信息记得更牢（因为获得丰富的精细加工）。

> **MatLens 的映射**：
> - **提取练习 → "记忆确认"机制**。用户看到 Agent 注入的记忆后，如果有误，主动纠正一次，比让 Agent 永远依赖一条错记忆价值高得多。这正是前端 P0 设计的理论依据。
> - **间隔效应 → 记忆复习调度**。一条记忆在第 1 天、第 3 天、第 7 天、第 21 天被"看见"一次，保留曲线变平。
> - **自我参照效应 → 强化科研记忆的"用户锚定"**。MatLens 的 `[用户]` 类别对应自我参照，天然应享有更高保留权重。

#### 睡眠与巩固（consolidation）

- **突触巩固**：分钟到小时级，突触连接改变
- **系统巩固**：数天到数年，皮层网络逐渐脱离海马体依赖
- **睡眠中大部分巩固发生**：海马体"重放"当天经历，与皮层纺锤波/慢振荡协调
- **睡眠剥夺**使新信息编码下降约 40%，巩固减弱
- **重要但不只是忠实复制**：睡眠提取 gist，反而会**增加** DRM 式虚假记忆

**海马体内的两个关键电路**：
- **模式分离**（pattern separation，齿状回）：把相似经历区分开
- **模式完形**（pattern completion，CA3）：从部分线索恢复完整记忆

> **MatLens 的映射**：
> - **模式分离 → 记忆去重**。两条记忆高度相似时（cosine > 阈值），必须触发合并而非并存。MatLens 现在没有。
> - **模式完形 → 部分线索召回**。用户只记得"上次那个 XPS 测试"而不记得材料名，混合检索 + 图谱邻接能恢复。
> - **离线巩固 → 记忆整理任务**。像 Mem0 的 "Dream"、A-MEM 的记忆演化、MemOS 的 MemCube 融合——**在非请求路径上批量做**。MatLens 已有 `on_pre_compress`、`on_session_end` 这些钩子位置，但没用来做巩固。

### 4.3 编码与提取：线索依赖

- **编码特异性原则**（Tulving & Thomson）：**提取的有效性取决于提取时可用线索与编码时线索的重叠度**
  - 情境依赖记忆：外部环境与学习场景匹配 → 更好
  - 状态依赖记忆：内部生理/情绪状态匹配 → 更好
  - **迁移适当加工**（transfer-appropriate processing）：编码时的心理操作与提取任务所需操作匹配 → 最佳
- **识别 vs 回忆**：识别（从选项中挑）比回忆（无提示产出）容易得多
- **提取可能失败的原因**：线索不匹配（cue-dependent forgetting）——记忆还在，但够不着

> **MatLens 的映射（这是最被低估的一节）**：
> - MatLens 目前的记忆写入，**几乎不记录"编码情境"**。一条记忆只存了文本 + 少量 metadata（channel、created_at），**没有记录它是在什么上下文中产生的**。
> - 结果就是：**向量检索用的是"语义相似"这一单一线索**，而语义相似只是众多提取线索中的一种。
> - **改造方向**：写入时同时记录 **实体线索（材料名、参数、文献 DOI）+ 情境线索（项目/论文阶段/时间）+ 情境操作（当时在做什么：表征解读/文献检索/大纲/写作）**。检索时按线索类型分别召回再融合。
> - 这比"上更大的 embedding 模型"的收益大得多——**因为纯稠密检索本质上只用了语义这一条线索**。
> - **迁移适当加工 → 记忆按"用途"分桶**。文献检索阶段该召回"我读过什么"，表征解读阶段该召回"我的样品数据"。`[实验]` 和 `[材料]` 混在一个扁平空间里，检索无法按阶段定向。

### 4.4 记忆的重构性与七宗罪

**巴特莱特（1932）《幽灵之战》**：给英国人讲北美原住民神话，回忆出来的不是"变模糊的副本"，而是**重构**——陌生元素被替换成熟悉元素，故事被重塑以符合既有的图式。**记忆是"想象式重构"，不是"从磁带回放"。**

**Schacter 记忆七宗罪**（Schacter 1999），以及它们在 Agent 记忆系统中的**一一对应工程映射**：

| 罪 | 认知含义 | **Agent 记忆系统对应故障** | MatLens 现状 |
|---|---|---|---|
| **易失性**（transience） | 时间流逝导致的衰退 | 保留策略问题：过期记忆不衰减，噪声持续占用检索位 | ❌ **完全没有** |
| **心不在焉**（absent-mindedness） | 编码时注意力不足 | **捕获缺口**：关键细节因为没有策略要求记录而根本没被记下 | ⚠️ 依赖 Agent 自主 `mem0_add`，无覆盖度保证 |
| **阻断**（blocking） | 存了但够不着 | **索引问题**：记录存在但查询触达不到 | ⚠️ 纯向量近邻，BM25/图谱缺失 |
| **错误归因**（misattribution） | 内容对、来源错 | **溯源问题**：用户说的 / 文档说的 / 上次 Agent 说的混在一起 | ⚠️ 无来源字段，`metadata` 只有 channel |
| **暗示性**（suggestibility） | 接受外部暗示 | **提示注入面**：被污染的内容随每次检索被反复激活 | ❌ 无来源标记 + 有网页导入通道 |
| **偏差**（bias） | 当前信念重塑过去 | **畸变级联**：昨天的记忆被今天的先验改写 | ⚠️ 无版本、无"原文 vs 提炼"分离 |
| **持久性**（persistence） | 不该留的挥之不去 | **过度保留**：过时偏好/废弃方案持续被召回 | ❌ 无 |

**还有一个在 Agent 语境下特别致命的机制**：

**再巩固（reconsolidation）**（Nader, Schafe & Le Doux 2000）：**提取一个已巩固的记忆会使它重新变得"可塑"（labile），必须重新稳定化才能持久——而且稳定化需要新的蛋白合成。** 换句话说：**"提取"本身就是一次写入机会**。

> **工程含义（非常重要）**：
> - 人的记忆在提取时会被当前语境重塑——所以"越用越歪"。
> - Agent 记忆若照搬这个机制，就会出现**自我污染**：一条记忆被检索一次，就可能带着当前上下文的偏见被改写一次，误差逐轮累积。
> - **防御策略**：**检索触发的修改必须是 append-only**。注解写到独立层，原记录保持字节稳定；由巩固任务（能看到完整注解集）决定什么可以被提升为正式记录。
> - MatLens 现状：`PATCH /api/memory/{id}` **直接原地覆盖**记忆文本，且 `mem_api` 没有版本历史。一旦被错误改写，**无法回滚、无法审计**。这是 MatLens 记忆系统里最具体的技术债之一。

**记忆的两层系统（互补学习系统）**：McClelland, McNaughton & O'Reilly (1995)：
- 快速的情景学习器（海马体）：迅速存储具体事件
- 缓慢的语义学习器（皮层）：从重复经验中逐渐提取稳定结构
- **情景层通过"批量学习而非覆盖"保护语义层免于灾难性干扰**

> **MatLens 的映射——这是本章最重要的架构建议**：
> - **两层结构**：
>   - **原文层（episodic）**：原始对话/实验记录逐字保留，永不改写。事实底座。
>   - **提炼层（semantic）**：LLM 从原文层蒸馏出的结构化事实与偏好，可被 UPDATE/仲裁，但始终标注"由哪条原文蒸馏而来"。
> - **MatLens 现在只有提炼层**——mem0 抽取完就把原文丢了。**这正是"摘要失真"和"无法溯源"的根源**。
> - MemPalace 的 "verbatim always" + Closet（AAAK 压缩索引）就是这套结构的现成实现，且**完全本地、零 API**——与 MatLens 部署形态一致。

**两系统互补在科研场景的收益**：新实验数据（情景）不会立刻污染"材料 NCM811 的最佳掺杂量是 3%"（语义），而是先进入原文层；只有在多篇独立情景都指向同一结论时，才提升为语义层事实。**这直接解决"实验数据一改一丢"和"旧结论污染新结论"两个科研痛点。**

### 4.5 人类记忆 → 工程映射总表

| 人类机制 | 心理学证据 | Agent 记忆工程实现 | MatLens 优先级 |
|---|---|---|---|
| 多重存储系统 | 工作记忆 7±2；长时程三分 | 分层 schema（working / episodic / semantic / procedural） | P1 |
| 组块 | Miller 组块理论 | 记忆条目大小规范 + 论文/实验为单位 | P1 |
| 遗忘曲线 | Ebbinghaus 1885 | 时间衰减检索降权（Mem0 Decay 模式） | P0 |
| 干扰（前进/倒向） | 干扰理论 | 写入时矛盾仲裁（UPDATE 而非并存） | P0 |
| 间隔效应 | 间隔 > 集中 | 记忆复习调度（1/3/7/21 天） | P2 |
| 提取练习效应 | Roediger & Karpicke 2006 | 记忆确认 UI（用户一键纠正） | **P0** |
| 生成效应 | 主动产出 > 被动阅读 | 让用户"确认并改写"记忆 | **P0** |
| 编码特异性 | Tulving & Thomson | 记录编码情境；多线索检索 | P1 |
| 迁移适当加工 | Transfer-appropriate | 记忆按用途/阶段分桶 | P2 |
| 模式分离 | 齿状回 | 高相似记忆合并（去重） | P1 |
| 模式完形 | CA3 | 部分线索召回（混合检索 + 图谱） | P1 |
| 睡眠巩固 | 睡眠中重放 | 离线巩固任务（非请求路径批量） | P2 |
| 两系统互补 | McClelland 1995 | 原文层 / 提炼层双层架构 | **P1** |
| 再巩固 | Nader 2000 | 检索触发的修改必须 append-only + 版本化 | **P0** |
| 七宗罪 | Schacter 1999 | 遗忘/捕获/索引/溯源/注入/畸变/过保留 七个防线 | 全阶段 |
| 生成式重构 | Bartlett 1932 | 区分"原文"与"提炼"，显式标注后者是解释 | P1 |

---

## 5. 优化建议：优先级矩阵与实施方案

### 5.1 总览：按投入产出比排序

```
                    投入低                              投入高
              ┌──────────────────────────────────────────────────────┐
              │  P0-A 记忆中心界面          P1-C 双层架构            │
   收益高     │  P0-B 混合检索+RRF          P1-D 程序性记忆(SOP)    │
              │  P0-C 冲突仲裁+版本化       P1-E 离线巩固任务        │
              │  P0-D 记忆确认机制                            P2-F 复习调度│
              ├──────────────────────────────────────────────────────┤
              │  P0-E 溯源与安全加固         P2-G 记忆图谱时序化      │
              │  P1-B 记忆类型学重构         P2-H 评测 harness      │
              └──────────────────────────────────────────────────────┘
```

### 5.2 P0 —— 第一阶段（2 周内可交付，不涉及记忆架构重构）

#### P0-A：记忆中心前端界面（最大杠杆）

**问题**：`mem_api.py` 已有 CRUD，`design/prototype/` 已有完整前端实现，但**两者都没接到生产链路**上。

**前置工作（必须先做，1–2 天）**：
1. **router 挂载**：`matlens_cli/web_server.py` 挂载 `mem_api` router，或**统一改路径**为 `/api/memories`（推荐，彻底避开与 `web_server.py:13508` 的 `GET /api/memory` provider 状态路由冲突）
2. **分页参数**：给记忆列表接口补 `offset/limit`（现在 `top_k` 上限 100 且无分页，`mem_api.py:185-198`）；同时**修掉 top_k 静默截断**（API 允许 100，provider 截 50）
3. **字段补齐**：在 `plugins/memory/mem0/__init__.py:583-584` 的返回结构里补上 `created_at` / `metadata` / `updated_at`（当前只回 `id/memory/score`，溯源信息在 provider 层就丢了）
4. **真实计数**：`_best_effort_count` 改为后端真实计数（mem0 提供了 count 接口），不要用抽样近似
5. **注入溯源**：补 `GET /api/memories/last-injection` 或在聊天响应里带 `memory_trace`（`MemoryManager.prefetch_all` 已有结果，未透传）

**方案**：把 `design/prototype/` 的记忆管理页**移植进 `web/src/pages/MemoryPage.tsx`**（React + shadcn/ui 风格），左栏新增「记忆」入口。

**移植时的对照表**：

| 原型资产（原生 JS） | 移植目标（React） | 需补的缺口 |
|---|---|---|
| `app.js:2823-2945` `loadMemories`/`renderMemCats`/`renderMemories` | `web/src/pages/MemoryPage.tsx` + `lib/api.ts` | 接口路径、错误态、空态 |
| `index.html:2123-2150` 记忆管理页 | 页面骨架 | 分页（原型没有） |
| `index.html:2129` `#mem-search` | 搜索框 | 搜索要接真实 `q` 参数 |
| `index.html:1799` 右侧「记忆」标签页 | `ChatPage.tsx` 右栏 | **本轮注入记忆可视化（原型也没有）** |
| `index.html:1629` 左栏「记忆图谱」 | 新页面 | **接 `graph_api` 的 graph.json（原型也没接）** |
| `index.html:1419` 记忆召回提示条 | ChatPage 组件 | 接入真实 injection trace |
| `index.html:1719-1721` 命令面板「翻阅记忆」 | `web/src/app/command-palette/` | 路由 |

**必须新增的 5 个区块**（原型都没有，是本次的增量）：

1. **记忆流（Memory Stream）**
   - 列表展示，每条：内容、类别标签、创建时间、来源、访问次数、最后访问时间
   - 筛选：按类别 / 时间范围 / 来源 / 检索关键词
   - **必须分页**（当前 `GET /api/memory` 最多 top_k=100，没有分页参数 —— 需后端补 `offset/limit` 或游标）
   - 搜索框直接复用 `GET /api/memory?q=...`

2. **本轮注入可视化（Injection Trace）**
   - 聊天页显示"本轮注入了 N 条记忆"，点击展开看具体是哪几条、来自哪条原文
   - **依据**：§4.3 提取练习效应 + 可解释性。MemPalace、Hindsight、PRIME 全部强调这点
   - 数据来源：`MemoryManager.prefetch_all` 已有结果，但**目前没有透传到 API 层** → 需后端补一个 `/api/memory/last-injection` 或在聊天响应里带 `memory_trace` 字段

3. **纠正与确认（Correction）**
   - 每条记忆可**编辑 / 删除 / 标记"这条不对"**
   - **纠正一次 = 一次提取练习**，且触发底层 UPDATE（不是新增一条矛盾记忆）
   - 表格行内编辑（不跳页）

4. **冲突与过期提示（Contradiction Radar）**
   - 当两条记忆语义高度相似但内容冲突时，高亮提示"这可能是过期/矛盾记忆"
   - 给出「保留新的 / 保留旧的 / 两条都留 / 都不是」四个动作
   - **依据**：Schacter 错误归因 + 倒向干扰 + Mem^p 的结构化教训

5. **溯源徽标（Provenance Badge）**
   - 每条记忆显示来源徽标：👤 用户陈述 / 📄 文档导入 / 🤖 Agent 推断 / 🔗 来自记忆 X
   - 推断类记忆视觉上要**可区分**（这直接对应"事实 vs 信念"分离，Hindsight 的 opinion network 思路）

**实现要点**：
- 复用 `web/src/lib/api.ts` 的 `fetchJSON` 封装，新增 `listMemories` / `addMemory` / `updateMemory` / `deleteMemories`
- 设计基线：桌面端 `apps/desktop/src/styles.css` 用 **shadcn/ui + Tailwind CSS v4 + Radix UI**，约 65 个 `--ui-*` CSS 变量（`--ui-primary` / `--ui-background` / `--ui-border` / `--ui-muted-foreground` / `--ui-card` / `--ui-destructive` / `--ui-warning` / `--ui-success` / `--ui-radius` / `--ui-font`）；原型 `design/prototype/index.html` 用 `--ml-*` 变量（`--ml-accent` / `--ml-bg` / `--ml-panel` / `--ml-border` / `--ml-text` / `--ml-dim`）。**移植时以 `web/src/index.css` 的实际 token 为准**，不要引入第三套变量体系
- 组件复用：`web/src/components/MemoryPressureBanner.tsx`（状态条样式）、`ConfirmDialog.tsx`（删除确认）、`DeleteConfirmDialog.tsx`（删除确认）、`AutoField.tsx`（表单）
- i18n：`web/src/i18n/zh.ts` + `en.ts` 同步补词条（`types.ts` 是类型源）

**成本**：**2–3 天**（原型移植 + 后端契约补齐）。比"从零设计"的 3–5 天省一半。

#### P0-B：混合检索 + RRF 融合

**问题**：`OSSBackend.search` 只有单一向量检索（`plugins/memory/mem0/_backend.py:280-282`）。

**方案**：在 MatLens 侧（不改 mem0 内部）加一层检索编排：

```
query → 多路召回 → RRF 融合 → (可选)cross-encoder 重排 → top-k
        ├─ 稠密向量（mem0 search）
        ├─ BM25 / 全文（关键词、材料名、参数名、DOI）
        ├─ 时间邻近（最近 N 天内 + 时间衰减）
        └─ 图谱邻接（learning_graph 邻居）
```

**RRF 公式**（标准做法，k=60）：
```
RRF(d) = Σ_i 1 / (k + rank_i(d))
```

**为什么必须做**：arXiv:2607.16848 实测在科学论文语料上 BM25 单独贡献最高 **+0.5 分**（10 分制），且能救回 dense 检索漏掉的精确字符串（5.0 → 10.0）。材料化学语料里"LSM"、"GDC"、"YSZ"、具体掺杂比例、DOI 这些**稀有字面形式极多**，正是 BM25 的主场。

**成本**：3–5 天。MatLens 已有 `matlens_state_search.py`（114KB）的全文检索能力可复用。

#### P0-C：冲突仲裁 + 版本化（append-only）

**问题**：`PATCH /api/memory/{id}` 原地覆盖，无版本历史，无冲突检测。

**方案**：
1. **版本化**：每条记忆加 `version`、`superseded_by`、`created_at`、`updated_at`、`source_memory_ids`
2. **append-only 注解层**：`PATCH` 不再直接改原记录，而是写一条 `annotation`（关联到原 id）。原记录字节稳定。UI 上呈现"这条已被修正" + 可展开看历史
3. **写入时仲裁**：写入新事实前，用向量检索 top-10 相似旧记忆，若存在矛盾 → 走四操作（ADD/UPDATE/DELETE/NOOP），**与 mem0 底层语义对齐**，但把决策过程暴露给用户确认
4. **依据**：§4.4 再巩固（Nader 2000）——"提取即写入机会"意味着覆盖必须可回滚，否则单次错误改写会被后续所有检索反复放大

**成本**：3–5 天（后端为主）。

#### P0-D：记忆确认 / 纠正闭环（低成本高收益）

**方案**：在 P0-A 的界面上加两个轻量动作：
- **"这条记住了"** → 提升该记忆的"访问强度"（对抗遗忘曲线，做间隔复习调度的基础数据）
- **"记错了"** → 一键转 P0-C 的 UPDATE 仲裁

**依据**：提取练习效应（Roediger & Karpicke 2006）——主动纠正一次的记忆保留率远高于被动重读。这条**理论上收益最大、工程上最便宜**。

#### P0-E：溯源与安全加固

**修复点定位很关键**：`mem0_search` 的返回结构在 `plugins/memory/mem0/__init__.py:583-584` 就把 `created_at` / `metadata` 丢了——**溯源字段必须在 provider 层补，不能只在 API 层加**。同时 `_write_metadata`（`:389-392`）目前只写 `channel`，需要扩展。

**方案**：
1. **写入即打标**：`source_type`（user / document / agent_inference / imported_web）、`source_ref`（DOI / 文件路径 / session_id）、`confidence` —— 写入 `_write_metadata`
2. **返回带溯源**：修改 `plugins/memory/mem0/__init__.py:583-584` 的 items 构造，补回 `created_at` / `metadata` / `updated_at`
3. **检索结果携带溯源**：注入 prompt 的每条记忆带来源标记，让模型能区分"用户说的"和"我从资料推的"
4. **网页导入隔离**：从 `kb_api` 的 `/sources/oa`、`/web-import` 导入的内容标记为 `external_untrusted`，检索注入时用不同围栏声明
5. **删除级联**：删记忆 → 关联的注解、图谱边、摘要缓存同步清理

**依据**：
- Schacter 错误归因 + 暗示性
- arXiv:2604.01350：**正常使用下跨用户污染率 57–71%**；arXiv:2601.05504：投毒成功率 6–38%
- MemOS MemCube 的 provenance 字段
- Hindsight 的 world/experience/opinion 分离

**成本**：2–3 天。

### 5.3 P1 —— 第二阶段（3–4 周）

#### P1-C：双层记忆架构（原文层 / 提炼层）

**这是最具架构价值的一项，直接借鉴 MemPalace + McClelland 两系统互补。**

```
┌─ 原文层 (Episodic, append-only) ──────────────────┐
│  原始对话、实验记录、文献导入 —— 逐字，永不改写    │
│  存储：JSONL + 全文索引（FTS5）                    │
│  作用：事实底座、可溯源、可回溯、可重算             │
└───────────────────────┬───────────────────────────┘
                        │ 蒸馏（可重跑、可调参）
                        ▼
┌─ 提炼层 (Semantic, 有仲裁) ───────────────────────┐
│  结构化事实、偏好、结论 —— mem0 向量库              │
│  存储：mem0 + Qdrant                                │
│  每条必须携带 extracted_from → 指向原文层 id 列表   │
│  作用：检索直接命中，省 token                        │
└───────────────────────────────────────────────────┘
```

**收益**：
- 摘要失真可回溯（提炼错了能看原文）
- 记忆可重算（换 embedding 模型 / 换抽取 prompt 后从原文重跑，不用重积累累）
- 满足 §4.4 的"生成式重构"要求——显式区分原文与解释

**成本**：约 2 周（原文层存储 + 蒸馏管线 + 溯源打通）。

#### P1-B：记忆类型学重构

把当前的 `[用户] [实验] [材料] [结论]`（正则解析、正文前缀）改成**结构化字段**：

| 字段 | 取值 | 依据 |
|---|---|---|
| `subject` | `user` / `project` / `agent` | survey 2602.06052 的 subject 轴 |
| `function` | `factual` / `episodic` / `procedural` / `working` | Squire 陈述/非陈述二分 + survey cognitive mechanism 轴 |
| `domain` | `ncm811` / `sofc` / `perovskite` / `sodium_ion` | MatLens 现有研究方向分类 |
| `phase` | `search` / `outline` / `writing` / `review` / `experiment` | 迁移适当加工——按用途分桶 |
| `encoding_context` | 抽取时的上下文线索（时间/项目/论文阶段） | 编码特异性原则 |
| `source_type` / `source_ref` / `confidence` | 见 P0-E | MemCube / Hindsight |
| `version` / `superseded_by` / `access_count` / `last_accessed` | 见 P0-C | 再巩固 |

**成本**：schema 变更 + 迁移，约 1 周（与 P1-C 同期做）。

#### P1-D：程序性记忆（科研 SOP）—— **领域独有的差异化护城河**

**这是 MatLens 相对通用 Agent 框架最有机会做出壁垒的一项。**

**依据**：Mem^p (arXiv:2508.06433) 定义程序性记忆 = "从经验轨迹中蒸馏出的、可复用的教训"。在 ALFWorld 上：任务完成率 **42.14% → 77.86%（+35pp）**，平均步数 **23.76 → 15.01（−37%）**；且**跨模型迁移**（GPT-4o 提取的教训让 Qwen2.5-14B 提升 5pp）——教训编码的是工作流知识，不是模型特定的推理模式。

**在 MatLens 的具体形态**——科研 SOP 卡片：

```
触发条件：XRD 出现异常峰
检查顺序：
  1. 先查是否混入 CuO 杂相（最容易误判）
  2. 再查 2θ 零点校准漂移
  3. 最后查样品致密度不足
理由：前两项覆盖约 80% 的情况，验证更快
来源：2026-08 那次 SOFC 样品误判（见记忆 #123）
置信度：0.9
```

**与 Mem^p 的差异化**：MatLens 的 SOP 应该**与具体材料体系绑定**（"LSM 体系的制备 SOP"而非泛化的"实验 SOP"），且**带文献引用**（"依据 Zhang et al. 2024 的相图"）。这是通用 Agent 做不到的。

**实现**：
- 触发：从 `agent/learning_mutations.py` + `learning_graph.py` 的失败/纠正事件提炼
- 存储：结构化 JSON 卡片（遵循"认知类型 × 存储格式正交"原则——同一 SOP 既可存简单笔记也可存 JSON Card）
- 注入：在论文工作流的对应阶段（检索/大纲/写作/审稿）定向注入
- 前端：在 P0-A 的记忆中心加「SOP」tab

**成本**：约 2 周。

#### P1-E：离线巩固任务（Sleep Consolidation）

**方案**：在非请求路径上批量做（复用 MatLens 已有的 `on_session_end` / `on_pre_compress` / cron 机制）：
- 夜间或低峰期批量：去重（模式分离）、合并、矛盾检测、提炼层重算、EPISODIC → SEMANTIC 提升判定
- **依据**：Rasch & Born (2013)——巩固发生在离线静息态而非执行期。Mem0 的 "Dream"、A-MEM 的记忆演化、MemOS 的 MemCube 融合都是这个模式
- **注意**：论文提示"睡眠巩固提取 gist 会增加 DRM 式虚假记忆" → 提炼必须保留原文指针，且**冲突项不得自动提升**

**成本**：约 1 周。

### 5.4 P2 —— 第三阶段（1–2 个月）

| 编号 | 建议 | 依据 |
|---|---|---|
| P2-F | **记忆复习调度**：按 1/3/7/21 天曲线安排"记忆确认"提醒 | 间隔效应 + 遗忘曲线；数据来自 P0-D 的"这条记住了"点击 |
| P2-G | **记忆图谱双时态化**：learning_graph 加 `valid_from` / `valid_to` / `invalidated_by`，支持"在我改用 B 方案之前用的是哪个" | Zep/Graphiti 双时态模型；科研场景版本管理刚需 |
| P2-H | **评测 harness**：按 arXiv:2607.16848 的十项要求建评测 | 见 §7 |
| P2-I | **多跳检索**：HippoRAG 式 PPR 在学习图谱上做单步多跳 | 科研问题常需跨文献综合；HippoRAG 比迭代检索便宜 10–30× |
| P2-J | **语义化原文层**：给实验记录/文献做实体标注，建立「实体-参数-结论」结构化索引 | 结合 §4.3 编码特异性，让检索能按"材料+参数+结论"定向命中 |
| P2-K | **provider 选型收敛**：8 个 provider 插件对用户是认知负担 | 建议默认 mem0（本地）+ 提供 Hindsight 作为"文献模式"选项，隐藏其余 |

### 5.5 实施顺序建议

```
第 1 周   P0-E 溯源打标（先做，因为后续所有改造都依赖它）
         └→ P0-B 混合检索（后端）
第 2 周   P0-A 记忆中心前端（并行）
         └→ P0-C 冲突仲裁 + 版本化（后端）
第 3 周   P0-D 记忆确认闭环（依赖 P0-A）
         └→ P1-B 类型学重构（schema 迁移）
第 4-5 周 P1-C 双层架构（原文层 + 蒸馏管线）
第 6-7 周 P1-D 程序性记忆 SOP
第 8 周   P1-E 离线巩固任务
之后      P2 系列
```

---

## 6. 前端设计：记忆中心界面方案

### 6.1 信息架构

```
左栏
└─ 记忆（新增）
   ├─ 记忆流      （默认）
   ├─ 科研 SOP    （P1-D 后可用）
   ├─ 注入记录    （本轮/历史注入回溯）
   └─ 统计与体检  （条数、分类分布、过期预警、冲突预警、存储占用）
```

### 6.2 记忆流主界面

```
┌─────────────────────────────────────────────────────────────────┐
│ 记忆  [🔍 搜索记忆…            ]  分类▾  来源▾  时间▾   [+ 手动添加]│
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 📌 [材料] NCM811 在 800°C 时的最优掺杂量是 3% Al            │ │
│ │      来源:👤用户陈述 · 2026-08-14 · 被召回 12 次 · 最近 3 天前 │ │
│ │      ⚠️ 可能与下方 1 条冲突                          [编辑][删除]│ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 🤖 [结论] 上次 XPS 表明表面存在 Na2CO3 杂相                │ │
│ │      来源:🔗来自记忆 #128（实验记录） · 2026-09-02           │ │
│ │      置信度 0.72 · 被召回 3 次                              │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                        ...（分页，每页 30 条）                 │
└─────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- **来源徽标用颜色 + 图标双编码**：👤用户陈述（蓝）/ 📄文档（绿）/ 🤖Agent推断（灰）/ 🔗派生（紫）。**Agent 推断的记忆必须视觉可区分**——这直接对应"事实 vs 信念"分离，也是用户信任的前提
- **被召回次数 / 最近召回时间**：这是间隔调度和衰减权重的可视化，也是用户判断"这条还有用吗"的依据
- **冲突提示用 ⚠️ 内联而非弹窗**：不打断浏览，但足够醒目

### 6.3 注入溯源（ChatPage 内）

```
┌─ 用户消息 ─────────────────────────────────────────┐
│ 我之前那个 SOFC 电解质用的什么掺杂？                 │
└─────────────────────────────────────────────────────┘
┌─ 助手回复 ─────────────────────────────────────────┐
│ ...（回答）...                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🧠 本轮参考了 3 条记忆        [查看]              │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
        ↓ 点击展开
┌─────────────────────────────────────────────────────┐
│ 🧠 本轮注入的记忆（3 条）                             │
│ ① [材料] YSZ 中 3 mol% Y2O3 掺杂电导率最高  →  #142 │
│    📄来源：Zhang et al. 2024 · 已在原文层归档       │
│ ② [实验] 你 6 月测的样品是 8YSZ 不是 10YSZ  →  #87 │
│    👤来源：用户陈述 · 2026-06-03                    │
│ ③ [结论] 电导率测试在 700°C 下做的              →  #203 │
│    🔗派生自：#142                                   │
│ [✓ 这几条记住了]  [⚠️ 有记错的，点这里纠正]          │
└─────────────────────────────────────────────────────┘
```

**这两个按钮是整个前端设计的核心**：
- **"这几条记住了"** = 一次提取练习（§4.2）→ 提升访问强度 → 抗遗忘曲线
- **"有记错的"** = 触发 UPDATE 仲裁（§4.4 再巩固防御）→ 原记录保持字节稳定，写入注解层

### 6.4 与现有 UI 的一致性

**三套前端的设计基线**（移植时不要引入第四套变量体系）：

| 前端 | 技术栈 | 变量体系 | 组件库 |
|---|---|---|---|
| `web/`（主 Web 端） | React + TypeScript + Vite | `web/src/index.css` 的 CSS 变量 | shadcn/ui + Radix UI |
| `apps/desktop/`（桌面端） | React + TS + Electron | `apps/desktop/src/styles.css` 约 **65 个 `--ui-*`** 变量：`--ui-primary` / `--ui-background` / `--ui-border` / `--ui-muted-foreground` / `--ui-card` / `--ui-destructive` / `--ui-warning` / `--ui-success` / `--ui-radius` / `--ui-font` | shadcn/ui + Tailwind CSS v4 + Radix UI |
| `design/prototype/`（原型） | 原生 JS + CSS | `--ml-*` 变量：`--ml-accent` / `--ml-bg` / `--ml-panel` / `--ml-border` / `--ml-text` / `--ml-dim` | 无（手写 CSS） |

**移植原则**：以 `web/src/index.css` 实际 token 为准；原型里已确认的类名（`.mem-item` / `.mem-cat` / `.mem-badge` 等，CSS 定义在 `design/prototype/index.html:1384-1420` 附近的「记忆图谱 / 记忆管理 / 记忆召回提示条」三段）作为**视觉参考**，不直接搬 CSS。

**具体复用点**：
- **左栏布局**：沿用 `web/src/App.tsx` 现有左栏导航结构，新增一项，不改动既有布局
- **卡片样式**：参照 `web/src/components/MemoryPressureBanner.tsx` 与 `SystemPage.tsx` 的卡片/徽标/色调映射（`destructive` / `warning` / `success` / `secondary`）
- **删除确认**：复用 `web/src/components/ConfirmDialog.tsx` 与 `DeleteConfirmDialog.tsx`
- **行内编辑表单**：参照 `AutoField.tsx` / `ConfigPage.tsx`
- **命令面板**：参照 `web/src/app/command-palette/index.tsx`，把原型的「翻阅记忆」条目接进去
- **i18n**：`web/src/i18n/zh.ts` + `en.ts`（`types.ts` 是类型源，其他语言可先英文兜底）

### 6.5 桌面端（apps/desktop）

`apps/desktop/src/app/settings/memory/provider-config-panel.tsx` 目前是 provider 配置面板。桌面端可作为第二阶段目标，把记忆中心做成独立 pane（参考 `apps/desktop/src/app/starmap/` 的独立视图范式）。

**一个需要注意的坑**：桌面端 `apps/desktop/src/app/settings/constants.ts:680-681` 声明的 memory 设置项只有 `memory.memory_enabled` 与 `memory.user_profile_enabled`，**缺少后端已支持的 `auto_write` 和 `graph_auto_build`**（`config/matlens.yaml:815-817` 与 `mem_api.py:242-243` 都有）。这两个开关在桌面端设置页不可见——补记忆设置时应一并补上。

---

## 7. 评测方案：怎么证明这些改动有用

**这是 MatLens 目前完全没有、但必须补的一环。** 没有评测，上面所有建议都是"看起来更好"。

### 7.1 直接借用 arXiv:2607.16848 的方法论

**核心原则：科学记忆评测不应是"哪个架构分数高"的排行榜，而应是"在固定检索预算、固定摄取粒度、固定合成器下，哪个系统能最有效地恢复忠实、充分、相关、且预算可控的证据上下文"。**

### 7.2 MatLens 记忆评测集（建议 60–100 题）

**语料**：MatLens 现有材料化学文献库 + 模拟的实验对话历史
- L1（单篇单跳，如"Zhang 2024 用的什么掺杂量"）→ 预期饱和，**不作为区分指标**
- L2（单篇机制/多部分枚举，如"LSM 的缺陷有哪些"）
- L3（跨文献综合，如"SOFC 电解质有哪些主流掺杂策略，各自代价是什么"）

**rubric 审计**（照搬论文做法）：首版 76 题中曾有 **37 题至少一个类别缺陷**（A 事实无法在引用论文验证 11 / B 依赖语料外数据 5 / C 依赖易变值 3 / D 过度精确 12 / E 参数知识可答 5 / 多类别 6）。**MatLens 的 rubric 必须先审计再使用**，否则评测结果不可信。

### 7.3 必测的六项能力（对应不同 benchmark 的能力划分）

| 能力 | 对标基准 | 为什么对 MatLens 重要 |
|---|---|---|
| **精确检索** | LongMemEval 信息提取 | 基础功 |
| **矛盾消解** | BEAM 独有 | **科研核心**：新材料数据推翻了旧结论 |
| **事件排序** | BEAM 独有 | **科研核心**："我先试了 A 方案还是 B 方案" |
| **选择性遗忘** | MemoryAgentBench 第 4 项 | **科研核心**：废弃的实验方案应被遗忘但结构保留 |
| **测试时学习** | MemoryAgentBench 第 2 项 | 越用越准 |
| **记忆改变决策** | MemoryArena / STATE-Bench | **终极检验**：记忆是否真的帮上了论文写作 |

### 7.4 消融实验设计（证明每一项改动有用）

固定语料、固定预算（10K / 30K / 50K 字符）、固定 synthesizer（DeepSeek）、固定 judge：

| 实验 | 对照 | 预期 |
|---|---|---|
| E1 混合检索 | dense vs dense+BM25 vs dense+BM25+RRF | BM25 在材料语料上应显著（论文实测最高 +0.5） |
| E2 冲突仲裁 | 有/无 UPDATE 仲裁 | 矛盾消解题应大幅提升 |
| E3 双层架构 | 仅提炼层 vs 原文+提炼 | L3 综合题 + 可溯源率 |
| E4 遗忘策略 | 无衰减 vs 时间衰减 vs 衰减+访问强化 | 精度/陈旧率权衡曲线 |
| E5 SOP 记忆 | 有/无程序性记忆注入 | 论文质量指标（写作阶段） |
| E6 注入可见性 | 有/无注入溯源 UI | 用户纠正率、纠正后准确率 |

### 7.5 报告纪律（抄 MemPalace 的诚实度）

- **同时报 native 与 budget-targeted 两条轨道**
- **报告每次查询的实际返回字符/token 数**
- **配对 bootstrap（10,000 次）+ 95% CI**，CI 含 0 即称平局
- **不把 10 分制内 1–2 分以内的差异当真实排名**（论文实证：此区间与人工判断一致率仅 50%；≥4 分时 100%）
- **base model 既作性能下限也作参数污染探针**
- **L1/L2/L3 分层报告**，不只报总均值

---

## 8. 风险与不做的事

### 8.1 明确不做

| 不做 | 理由 |
|---|---|
| **不引入 GraphRAG 全量重构** | arXiv:2607.16848 实测：固定预算后复杂架构优势统计上消失；GraphRAG 只支持批量重建，与 MatLens 频繁更新场景冲突 |
| **不自研向量数据库** | MatLens 已有 mem0+Qdrant+kb.py 自研 JSON 三套存储，已经是技术债，**不要再加第四套** |
| **不做"更拟人化"的记忆叙事** | 科研用户要的是"我说的哪句话被存了、存对没有"，不是拟人化的agent diary |
| **不追求 8 个 provider 全功能对齐** | 用户认知负担；应收敛到 2 个（mem0 本地 + Hindsight 文献模式） |
| **不在没有评测的情况下大改** | §7 的评测集必须先建 |

### 8.2 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 双层架构导致存储翻倍 | 高 | 中 | 原文层用 JSONL + FTS5，不用向量库，成本可控 |
| 记忆条目数增长后前端卡顿 | 中 | 中 | 必须分页 + 虚拟列表；不一次性拉全量（当前 `top_k<=100` 已是无分页的隐患） |
| 混合检索增加延迟 | 中 | 中 | BM25 走 SQLite FTS5，毫秒级；RRF 开销可忽略 |
| 冲突仲裁误判导致错误覆盖 | 中 | **高** | P0-C 的 append-only 设计：原记录字节稳定，只写注解；UI 提供撤销 |
| 多 provider 并存导致语义分裂 | 中 | 中 | 收敛到默认单 provider + 显式切换；写入时打 provider 标记 |
| 上游 mem0 升级破坏 `_backend.py` | 中 | 中 | `_backend.py` 已有注释说明 mem0 2.0.x schema 限制；升级时重点回归 |
| 记忆库成为注入通道 | 中 | **高** | P0-E 溯源 + `external_untrusted` 隔离 + 围栏分层 |

### 8.3 依赖与前置

- **P0-A 依赖**：后端补 `GET /api/memory` 分页参数、`/api/memory/last-injection` 或聊天响应带 `memory_trace`
- **P1-C 依赖**：需要存储选型定稿（建议 JSONL + SQLite FTS5，不引入新向量库）
- **P1-D 依赖**：`learning_mutations.py` 的失败事件需带足够上下文（材料、参数、步骤）
- **全部 P1+ 依赖**：§7.2 评测集先建（否则无法判断改动是否有效）

---

## 9. 参考文献

### AI 长期记忆论文（按主题）

**综述与分类学**
1. Huang, W.-C. et al. (60+ authors). *A Survey of Agent Memory in the Second Half: Towards Self-Evolving and Long-Horizon Agents.* arXiv:2602.06052. TMLR. (v4, 2026-08-04). — 三轴分类：substrate / cognitive mechanism / subject
2. *Memory in the Age of AI Agents.* arXiv:2512.13564 (2025-12). — 47 作者；Forms / Functions / Dynamics 三轴；指出 procedural memory 是最大缺口
3. Wu, Y. et al. (Huawei Noah's Ark Lab). *From Human Memory to AI Memory: A Survey on Memory Mechanisms in the Era of LLMs.* arXiv:2504.15965 (2025). — Object / Form / Time 三维分类
4. Zhang, Z. et al. *A Survey on the Memory Mechanism of LLM-based Agents.* arXiv:2404.13501 (2024). — write / consolidate / read 操作视角
5. *A Survey on the Security of Long-Term Memory in LLM Agents: Toward Mnemonic Sovereignty.* arXiv:2604.16548 (2026). — 记忆即攻击面；memory 是重构非存档

**架构与机制**
6. Chhikara, P. et al. *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory.* arXiv:2504.19413 (2025-04-28). — 提取-更新两阶段，ADD/UPDATE/DELETE/NOOP
7. Packer, C. et al. *MemGPT: Towards LLMs as Operating Systems.* arXiv:2310.08560 (2023).
8. Xu, W. et al. *A-MEM: Agentic Memory for LLM Agents.* arXiv:2502.12110 (v11, 2025-10-08). — Zettelkasten；DialSim F1 3.45；token −85~93%
9. Li, Z. et al. *MemOS: An Operating System for Memory-Augmented Generation (MAG) in LLMs.* arXiv:2505.22101 (2025-05-28).
10. Li, Z. et al. *MemOS: A Memory OS for AI System.* arXiv:2507.03724 (v4, 2025-12-03). — MemCube（provenance + versioning）
11. *Mem^p: Procedural Memory for LLM Agents.* arXiv:2508.06433 (2025-08). — ALFWorld 42.14%→77.86%；步数 −37%；跨模型迁移 +5pp
12. *MemMachine.* arXiv:2604.04853 (2026). — 事实真值衰减与周期性校验
13. *PRIME.* arXiv:2604.07645 (2026). — 无梯度工作记忆演化
14. Gutiérrez, B.J. et al. *HippoRAG.* arXiv:2405.14831 (NeurIPS 2024). — PPR 单步多跳
15. Gutiérrez, B.J. et al. *From RAG to Memory: Non-Parametric Continual Learning for LLMs (HippoRAG 2).* arXiv:2502.14802 (2025).
16. Edge, D. et al. *From Local to Global: A Graph RAG Approach to Query-Focused Summarization.* arXiv:2404.16130 (2024). — 仅批量重建
17. Guo, G. et al. *LightRAG.* arXiv:2410.05779 (EMNLP 2025). — 增量更新，token 低 10–100×
18. Sarthi, P. et al. *RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval.* arXiv:2401.18059 (ICLR 2024).
19. *Hindsight* (Vectorize.io & Virginia Tech). — 四网络（world/experience/observation/opinion）+ TEMPR(4路 RRF) + CARA；LongMemEval-S 83.6% vs GPT-4o 全上下文 60.2%；BEAM 10M 64.1% vs 40.6%
20. *A Temporal Knowledge Graph Architecture for Agent Memory (Zep).* arXiv:2501.13956 (2025). — 双时态
21. *Memory in the Age of AI Agents — 记忆排行榜方法论批评.* arXiv:2602.19320 (2026).

**评测基准**
22. Maharana, K. et al. *Evaluating Very Long-Term Conversational Memory of LLM Agents (LoCoMo).* ACL 2024.
23. Wu, D. et al. *LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory.* arXiv:2410.10813 (ICLR 2025).
24. Tavakoli, S. et al. *BEAM.* arXiv:2510.27246 (2025, 预印本). — 矛盾消解 + 事件排序；10M token
25. Hu, X. et al. *MemoryAgentBench.* arXiv:2507.05257 (2025). — 含选择性遗忘
26. *MemoryArena.* arXiv:2602.16313 (2026). — 主动记忆 vs 被动记忆；766 任务
27. *STATE-Bench.* Microsoft (2026-05).
28. *Mem2ActBench.* — MemArena 的相关基准
29. *HaluMem.* — 记忆形成阶段幻觉
30. **★** *Beyond Memory Leaderboards: Evaluating Scientific Memory as Budgeted Context Restoration.* arXiv:2607.16848 (2026). — **本报告最关键参考文献**：科学论文语料、8 系统对比、预算受控实验、评测 harness 十项要求、judge 分辨率约 1 分

**安全**
31. *No Attacker Needed* — 跨用户污染率 57–71%. arXiv:2604.01350 (2026)
32. *记忆投毒攻击.* arXiv:2601.05504 (2026). — 成功率 6–38%
33. *When Continual Learning Meets Memory.* arXiv:2604.27003 (2026). — 前向迁移 −9.5%

### 人类记忆文献

34. Ebbinghaus, H. *Über das Gedächtnis.* Duncker & Humblot, 1885. — 遗忘曲线
35. Miller, G.A. *The Magical Number Seven, Plus or Minus Two.* Psychological Review, 1956. — 组块
36. Baddeley, A.D. *Human Memory: Theory and Practice.* — 工作记忆四成分
37. Squire, L.R. et al. *Memory Systems of the Brain.* — 陈述/非陈述二分；海马体与巩固
38. Tulving, E. & Thomson, D. *Encoding Specificity and Retrieval Processes.* Psychological Review, 1973. — 编码特异性
39. Roediger, H.L. & Karpicke, J.D. (2006). *Test-Enhanced Learning.* Psychological Science. — 提取练习效应
40. Cepeda, N.J. et al. (2006). *Distributed Practice in Verbal Recall Tasks.* Psychological Bulletin. — 间隔效应
41. Delaney, P.F., Verkoeijen, P.P.J.L. & Spirgel, A. (2010). *Spacing and Testing Effects.* Psychology of Learning and Motivation 53:63–147.
42. Bjork, R.A. — 存储强度 vs 提取强度（Mem0 Memory Decay 的理论基础）
43. Bartlett, F.C. (1932). *Remembering: A Study in Experimental and Social Psychology.* — 记忆重构
44. Loftus, E.F. — 错误信息效应
45. Schacter, D.L. (1999). *The Seven Sins of Memory: How the Mind Forgets and Remembers.* Houghton Mifflin. — 七宗罪
46. Schacter, D.L. et al. (1998). *Constructive memory.* — 建构性记忆
47. Nader, K., Schafe, G. & LeDoux, J.E. (2000). *Fear memory reconsolidation in the human brain.* Nature. — 再巩固
48. McClelland, J.L., McNaughton, B.L. & O'Reilly, R.C. (1995). *Complementary learning systems.* Psychological Review. — 两系统互补
49. Rasch, B. & Born, J. (2013). *About sleep's role in memory.* Physiological Reviews. — 离线巩固
50. Craik, F.I.M. & Lockhart, R.S. (1972). *Levels of processing.* Journal of Verbal Learning and Verbal Behavior. — 迁移适当加工
51. Roediger, H.L. & McDermott, K.B. (1995). *Creating false memories.* Psychonomic Bulletin & Review. — DRM
52. Craik, K.J.L. et al. — 模式分离（齿状回）与模式完形（CA3）
53. Wilson, G.T. & Schooler, J.W. (1991). *Thinking too much: introspection can reduce the quality of preferences and decisions.* — 偏好表达准确性

### 开源项目

54. mem0ai/mem0 — Apache 2.0
55. getzep/graphiti — Apache 2.0
56. letta-ai/letta (前 MemGPT) — Apache 2.0
57. MemTensor/MemOS — 三类记忆统一
58. topoteretes/cognee — Apache 2.0
59. langchain-ai/langmem — MIT
60. agiresearch/A-mem — A-MEM 实现
61. mempalace/mempalace — 本地优先五层架构；LongMemEval R@5 96.6% raw / 98.4% hybrid held-out；MemBench R@5 80.3%；**README 主动披露 benchmark 局限与 "teaching to the test" 自我批评**
62. supermemoryai/supermemory
63. plastic-labs/honcho
64. vectorize-io/hindsight
65. OSU-NLP-Group/HippoRAG
66. HKUDS/LightRAG
67. microsoft/graphrag
68. parthsarthi03/raptor
69. basicmachines-co/basic-memory
70. memodb-io/memobase

### 项目内主要依据文件

- `agent/memory_manager.py` — MemoryManager 编排、prefetch、背景写入、上下文块构造
- `agent/memory_provider.py` — MemoryProvider 抽象基类
- `plugins/memory/mem0/_backend.py` — 三种后端模式（OSS / Self-hosted / Platform）
- `plugins/memory/mem0/__init__.py` — provider 实现、filters、system prompt block
- `plugins/memory/query_rewrite.py` — 查询改写
- `matlens_kit/api/mem_api.py` — 记忆 API（5 路由；`_normalize` 缺 created_at/metadata 透传）
- `matlens_kit/api/kb_api.py` — 知识库 API（21 路由）
- `matlens_kit/api/graph_api.py:91-110` — 从 mem0 拉记忆抽实体建图谱
- `matlens_kit/rag/kb.py` — 知识库（自研 VectorStore，384 维）
- `matlens_kit/plugins/local_rag/__init__.py`
- `agent/learning_graph.py`（skill 关系图）/ `agent/learning_mutations.py` — 学习图谱与变更
- `agent/background_review.py` — 后台审阅与记忆开关
- `matlens_state_search.py` — FTS5 + trigram + CJK 全文检索底座（混合检索可复用）
- `matlens_cli/web_server.py:13508-13533` — 生产入口的 `GET /api/memory`（provider 状态，与 mem_api 冲突）；`:6396-6480` provider 配置路由
- `matlens_kit/api/server.py:151` — 唯一挂载 mem_api router 的服务
- `config/matlens.yaml:809-830` — memory 配置段
- `web/src/pages/PluginsPage.tsx` — provider 配置 UI
- `web/src/pages/SystemPage.tsx` — 记忆状态与重置
- `web/src/lib/api.ts:1170-1201` — 记忆 API 客户端（当前仅用 getMemory/resetMemory）
- `web/src/index.css` — Web 端 CSS 变量（设计基线）
- `apps/desktop/src/styles.css` — 桌面端约 65 个 `--ui-*` 变量（shadcn/ui + Tailwind v4 + Radix）
- `apps/desktop/src/app/settings/constants.ts:680-681` — 桌面端 memory 设置项（缺 auto_write / graph_auto_build）
- `apps/desktop/src/app/settings/memory/provider-config-panel.tsx` — 桌面端 provider 配置面板
- `design/prototype/index.html:104-112,1384-1420,1629,1660,1719-1721,1799,2123-2150` — **原型已有的记忆管理 UI（重点复用资产）**
- `design/prototype/app.js:1635-1640, 2823-2945` — 原型记忆加载与渲染逻辑
- `design/frontend-design.md:104-112` — 记忆面板与记忆图谱的交互规范（已规划未实现）

---

*本报告基于 2026-10-29 对 D:\MatLens 代码的一手核实，以及对 30+ 篇论文、17 个开源项目的调研。所有涉及代码现状的论断均带文件:行号；论文数据均标注来源 arXiv 编号。第三方 benchmark 数字为厂商自报，未经独立复现，已在文中标注。*
