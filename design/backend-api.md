# MatLens 后端接口全景 + 前后端映射设计

> 2026-08-23 · 依据「先看后端，前端根据后端设计」原则
> 核心结论：前端所有功能都挂到**已存在的后端接口**上；缺失的只是一层 Web 服务封装（FastAPI + SSE），不重复实现业务。

## 一、后端真实能力（已核实，逐接口）

### 1. 对话引擎（run_agent.py · AIAgent）
| 接口 | 说明 | 前端用途 |
|---|---|---|
| `AIAgent(model, provider)` | 实例化（DeepSeek 等） | 会话初始化 |
| `run_conversation(message, stream_callback=cb)` | 对话主接口，回调接收流式增量 | **SSE 流式事件源** |
| `a.tools` | OpenAI 格式工具列表 `[{function:{name,description,parameters}}]` | 工具中心/事件流 schema |
| `_execute_tool_calls(...)`（agent/tool_executor.py 并发/顺序） | 工具执行（模型触发，自动） | 事件流工具卡（状态来自回调） |

> ⚠️ **关键约束**：Hermes 工具调用是**模型驱动自动执行**（execute_tool_calls 在对话循环内部）。前端要展示"思考→工具→结果"事件流，需在 `stream_callback` 之外再挂一层**事件钩子**（见"需新建"第 2 条），或在回调链路上注入事件。

### 2. 知识库（matlens_kit/rag/kb.py · KnowledgeManager）
| 接口 | 说明 |
|---|---|
| `list_kbs() / create(name) / delete(name) / switch(name)` | 知识库 CRUD |
| `add_document(path) / add_documents(paths)` | 文件入库（PDF/TXT/CSV/Excel 自动解析） |
| `query(question, top_k=5, score_threshold=0)` | 语义检索（返回分块+来源+相似度） |
| `stats()` / `knowledge_root()` | 统计（文献数/分块数） |
| `embed(texts)` | 嵌入（复用主 provider / 本地降级） |

→ **前端知识库页/引用角标/对话自动检索**全部直连。

### 3. 记忆（plugins/memory/mem0 + memory_manager）
| 接口 | 说明 |
|---|---|
| `Mem0MemoryProvider`（is_available/initialize） | 加载（OSS 本地：DeepSeek 提取 + fastembed + qdrant） |
| `backend.search(query, filters, top_k)` | 语义召回记忆 |
| `backend.add(messages, infer=True)` | 对话自动写记忆（sync_turn 已接） |
| `backend.update(memory_id, text) / delete(memory_id)` | 记忆编辑/删除 |
| `prefetch(query)` | 每轮对话前预召回注入 |

→ **前端右侧记忆面板 / 记忆图谱页**：search 列出记忆，update/delete 管理。

### 4. 会话（matlens_state.py · SessionDB + matlens_cli）
| 接口 | 说明 |
|---|---|
| SessionDB（state.db，sessions 表） | 底层存储（SQL 级） |
| resume / export / workspace_key | 会话恢复/导出（CLI 已有） |

→ **前端会话列表**需封装一层（见"需新建"第 1 条）。

### 5. 配置（matlens_cli/config.py）
| 接口 | 说明 |
|---|---|
| `load_config() / save_config(...) / get_config_value(key)` | 读改写 `~/.matlens/config.yaml` |
| `~/.matlens/.env`（DEEPSEEK_API_KEY） | 密钥 |
| `~/.matlens/mem0.json` | Mem0 配置 |

→ **前端设置页**直连：模型/provider/记忆开关/审批策略写入 config.yaml。

### 6. 已有 Web API（matlens_kit/ui/web/gradio_app.py，P2 产物）
`chat_fn / kb_refresh / kb_create / kb_switch / kb_upload / kb_stats / tools_render / tool_run / workflow_generate / workflow_record / settings_load / settings_save`
→ 这些函数**可复用为 FastAPI 端点**（同进程调核心，逻辑已验证）。

### 7. 论文工坊（老项目 mra/pipeline/paper_workflow.py，参考）
7 步 `topic→search→outline→write→quality→review→export`，stage 落库可重跑。
→ 新项目**尚无**论文工坊后端（P 阶段需新建，参考老项目模式：每步独立可重跑、paper_projects.stages JSON）。

## 二、前端功能 → 后端映射表

| 前端功能 | 后端接口 | 状态 |
|---|---|---|
| 发送消息/流式回答 | `run_conversation` + 事件钩子 | ✅ 已有 + 需事件层 |
| 停止生成 | 中断 run_conversation（线程/异步取消） | ⚠️ 需封装 |
| 工具调用卡片（事件流） | 事件钩子（tool_call/tool_result） | 🔧 需新建事件层 |
| 审批卡 | 工具执行前拦截（白名单/策略） | 🔧 需新建审批层 |
| 思考卡 | 模型 reasoning（流式回调分片） | 🔧 需事件层 |
| 引用角标 | `kb.query` 命中分块（来源/相似度） | ✅ 已有 |
| 会话列表/新建/分支/恢复 | SessionDB 封装 | 🔧 需新建 API |
| 知识库页（CRUD/上传/统计） | `list/create/delete/switch/add_document/stats` | ✅ 已有 |
| 工具中心（清单/schema/执行） | `a.tools` + tool_run | ✅ 已有 |
| 记忆面板（列表/搜索） | mem0 `search` | ✅ 已有 |
| 记忆编辑/删除 | mem0 `update/delete` | ✅ 已有 |
| 记忆图谱（蜘蛛网） | mem0 search 全量 + **实体抽取**（新） | 🔧 需新建图谱层 |
| 设置（模型/key/记忆/审批） | `config.py` 读写 + .env | ✅ 已有 |
| 实验方案 | `workflow_generate/record`（模板已有） | ✅ 已有 |
| 论文工坊 7 步 | **新后端**（参考 paper_workflow.py） | 🔧 需新建 |

## 三、需新建的服务层（FastAPI，前端专属，不碰核心）

```
matlens_kit/api/               ← 新增：Web 服务层
  server.py                    ← FastAPI app + 静态托管
  sse.py                       ← SSE 事件流端点（/api/chat/stream）
  events.py                    ← 事件钩子：从 run_conversation 回调链提取
                                 thinking/tool_call/tool_result/stream_text/done
  approval.py                  ← 审批层：工具白名单 + 策略 + 回传端点
  sessions_api.py              ← 会话 CRUD（封装 SessionDB）
  kb_api.py / mem_api.py / cfg_api.py / paper_api.py
```

| 新建 API | 职责 |
|---|---|
| `GET /api/sessions` · `POST /api/sessions` · `PATCH /api/sessions/{id}` | 会话列表/新建/改名/归档 |
| `POST /api/chat/stream`（SSE） | 事件流对话（事件钩子注入） |
| `POST /api/approval/{req_id}`（批准/拒绝） | 审批回传（approval.py 拦截工具执行） |
| `POST /api/chat/stop` | 中断生成 |
| `GET /api/memory` · `PATCH/DELETE /api/memory/{id}` | 记忆列表/编辑/删除 |
| `POST /api/graph/extract` | 记忆→图谱实体抽取（DeepSeek） |
| `GET /api/graph` | 返回图谱 JSON（节点/边，前端 vis-network 渲染） |
| `POST /api/paper/{project}/{stage}` | 论文工坊各阶段执行（新后端） |
| `GET/PUT /api/settings` · `POST /api/settings/test` | 配置读写 + 连接测试 |

## 四、关键设计决策

1. **同进程调核心**（延续 P2 拍板）：FastAPI 直接 import AIAgent/知识库/Mem0，数据天然互通，不引入 gateway 服务。
2. **事件流三层**：`run_conversation 回调 → events.py 归一化为七类事件 → SSE 推送`。审批是**唯一需要拦截工具执行**的地方（approval.py 在 execute_tool_calls 前插入决策点，策略 from config）。
3. **审批接入点**：Hermes 工具执行在 `agent/tool_executor.py`，最小侵入做法是**在事件钩子里对需审批工具先发 approval_request 事件、挂起执行、等回传**（approval.py 提供阻塞等待），或利用 Hermes 已有的审批/权限机制（查证后选最小侵入路径）。
4. **图谱数据流**：Mem0 记忆（带 [用户]/[实验]/[材料]/[结论] 标签）→ DeepSeek 抽实体/关系 → `~/.matlens/graph.json`（增量合并）→ 前端 vis-network。
5. **论文工坊**：新后端参考老项目 `paper_workflow.py`（阶段落库、可重跑），但**输入输出走新 AIAgent 事件流**（不在老项目里跑）。

## 五、实现顺序（与前端页面优先级对齐）

1. `server.py + sse.py + events.py`（M0：服务层 + 事件流）
2. `sessions_api.py`（会话）
3. `approval.py`（审批）
4. `kb_api.py / mem_api.py / cfg_api.py`
5. `graph_api.py`（记忆图谱）
6. `paper_api.py`（论文工坊，M6）
