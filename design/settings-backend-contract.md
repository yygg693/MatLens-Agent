# MatLens 设置页 ↔ 后端 接通契约（冻结，v1）

本文件是「设置页全部接通后端」工作的**唯一事实来源**。所有子任务必须严格遵循本
文件的字段名、默认值、接口形状与文件归属，不得各自命名。

- 后端根包：`D:\MatLens\matlens_kit\`
- 前端：`D:\MatLens\design\prototype\`（设置逻辑 `js/settings.js`）
- 持久化：`~/.matlens/config.yaml`（经 `matlens_cli.config.save_config(merge_existing=True)`），
  密钥仍写 `~/.matlens/.env`。
- 运行：`.venv\Scripts\python.exe -m matlens_kit.api.server --port 7896`
- 测试：`TestClient`（`from matlens_kit.api.server import app`），放 `tests/kit/`，
  用 `tmp_mat_home` 夹具；**不要**在测试里绑定 7896 端口。
  运行：`.venv\Scripts\python.exe -m pytest tests/kit -q`

## 1. 统一存储模块（基座新建）

新文件 `matlens_kit/settings_store.py`，**不得依赖 FastAPI**，业务模块只 import 它：

- `DEFAULTS`：第 2 节的完整嵌套默认 dict。
- `load_settings() -> dict`：以 DEFAULTS 为底，叠加 config.yaml **原始**读取值
  （用 yaml 直读，参照 `matlens_kit/ui/common.py::_load_raw_model_config`，避免
  `load_config()` 的 DEFAULT 合并把 dict 覆盖成字符串的同类问题）。返回完整嵌套 dict。
- `get_section(name) -> dict`：返回某一段（papers/kb/experiment/memory/general）。
- `update_settings(partial: dict) -> dict`：接收**嵌套部分更新**
  （如 `{"papers": {"cite_style": "ieee"}}`），与 config.yaml 现状深合并后持久化，
  返回更新后的完整 settings。整型字段强制 int，开关强制 bool。
- 持久化必须复用 `matlens_cli.config.save_config(cfg, merge_existing=True)` 单条写路径，
  并证明所有新键能往返（save→重新 load 值不变；这些键不在 DEFAULT_CONFIG 内，
  strip_defaults 不会删，但必须用测试验证）。

## 2. 规范字段（config.yaml 中的落点 / 默认值 / 前端控件 id）

### general（display.* 与 agent.*）
| 控件 id | config 路径 | 类型/取值 | 默认 |
|---|---|---|---|
| `theme-seg` / `theme-select` | `display.theme` | light/dark/system | dark |
| `gen-tool-progress` (toggle) | `display.tool_progress` | bool | true |
| `reasoning-effort` | `agent.reasoning_effort` | low/medium/high | medium |
| `max-turns` | `agent.max_turns` | int(10/25/50/100) | 25 |

### memory
| 控件 id | config 路径 | 类型 | 默认 |
|---|---|---|---|
| `mem-ext` (toggle) | `memory.memory_enabled` | bool（Mem0 总开关，**沿用既有键**） | true |
| `mem-auto-write` (toggle) | `memory.auto_write` | bool | true |
| `mem-graph` (toggle) | `memory.graph_auto_build` | bool | true |

### papers
| 控件 id | config 路径 | 取值 | 默认 |
|---|---|---|---|
| `paper-export-format` | `papers.export_format` | docx/tex/md | docx |
| `paper-cite-style` | `papers.cite_style` | gb7714/ieee/apa/acs | gb7714 |
| `paper-autosave` (toggle) | `papers.autosave` | bool | true |
| `paper-tone` | `papers.tone` | formal/concise/detailed | formal |

### kb
| 控件 id | config 路径 | 取值 | 默认 |
|---|---|---|---|
| `kb-embed-model` | `kb.embed_model` | local/text-embedding-3-small/text-embedding-3-large | local |
| `kb-chunk-size` | `kb.chunk_size` | int(500/800/1200) | 800 |
| `kb-chunk-overlap` | `kb.chunk_overlap` | int(50/100/200) | 100 |
| `kb-table-extract` (toggle) | `kb.table_extract` | bool | true |
| `kb-path` (readonly) | `kb.root` | 路径字符串 | `~/.matlens/knowledge` |

### experiment
| 控件 id | config 路径 | 取值 | 默认 |
|---|---|---|---|
| `exp-template` | `experiment.template` | standard/synthesis/characterization/electrochem | standard |
| `exp-autosave` (toggle) | `experiment.autosave` | bool | true |
| `exp-plot-format` | `experiment.plot_format` | png/svg/pdf | png |
| `exp-dpi` | `experiment.dpi` | int(150/300/600) | 300 |
| `exp-path` (readonly) | `experiment.db_path` | 路径 | `~/.matlens/experiments.db` |

## 3. HTTP 接口形状

### GET /api/settings（在现有返回上**扩展**，不得删旧字段）
保留现有：`model`、`providers`、`model_catalog`、`api_key_set`、`api_key_masked`、
`provider_keys`、`approval`、以及别名 `agent`、`memory`。新增/补全为：

```json
{
  "ok": true,
  "general": {"theme":"dark","tool_progress":true,"reasoning_effort":"medium","max_turns":25},
  "memory": {"enabled":true,"auto_write":true,"graph_auto_build":true,"provider":"mem0"},
  "papers": {"export_format":"docx","cite_style":"gb7714","autosave":true,"tone":"formal"},
  "kb": {"embed_model":"local","chunk_size":800,"chunk_overlap":100,"table_extract":true,"root":"~/.matlens/knowledge"},
  "experiment": {"template":"standard","autosave":true,"plot_format":"png","dpi":300,"db_path":"~/.matlens/experiments.db"},
  "about": {"version":"v0.2.0","tech_stack":"FastAPI · 原生 JS · Mem0","home":"~/.matlens/"}
}
```
（`memory.enabled` 继续映射 `memory.memory_enabled`，与旧 PUT 兼容。）

### PUT /api/settings
- 继续接受旧的扁平字段（model_default/model_provider/model_base_url/api_key/
  memory_enabled/reasoning_effort/max_turns/approval_*）。
- **新增接受嵌套部分更新**：`{"papers":{...}}`、`{"kb":{...}}`、`{"experiment":{...}}`、
  `{"memory":{...}}`、`{"general":{...}}`，只更新传入的叶子。
- 返回 `{"ok":true,"saved":true,"agent_reset":<bool>}`。
- 当 `agent.reasoning_effort` / `agent.max_turns` / `memory.memory_enabled` 变化时，
  调 `matlens_kit.ui.common.reset_agent()` 并把 `agent_reset` 置 true（模型切换逻辑保留）。

### 其他约定接口
- `GET /api/memory/status` → `{ok, enabled, provider, source, count, auto_write, graph_auto_build}`
  （记忆子任务在已注册的 mem_api 路由内实现；前端 probeMemory 改调此路径）。
- `POST /api/sessions/clear` → `{ok, cleared}`（关于/集成子任务实现，清空 state.db 会话与消息，不动记忆）。
- `POST /api/settings/reset` → `{ok}`（先时间戳备份 config.yaml/.env，再把设置恢复默认；
  按 UI 提示需重填 API key，故同时清除 provider 密钥；最后 reset_agent）。
- `GET /api/settings/backup` → `application/zip` 下载（含 config.yaml、.env、state.db、
  papers.db、experiments.db、graph.json、knowledge/ 元数据；大向量库可仅清单）。

## 4. 前端通用绑定（settings.js，仅基座允许改这个文件）

- 用一张「控件 id → (段, 键, 类型 toggle|select, 是否 int)」映射表驱动：
  页面加载时从 GET 回填（toggle 切 `.on` class；select 设 value；readonly path 赋值），
  变更时 PUT 嵌套部分更新（toggle 立即发；select 防抖 ~300ms）。
- **回填必须在 `mountMlSelect(...)` 之前设置隐藏 select 的 value**，再挂载自定义下拉并 sync，
  否则自定义控件显示旧值。
- 删除这些键的 localStorage 读写：mem_ext/mem_auto_write/mem_graph/paper_autosave/
  kb_table_extract/exp_autosave/ml_tool_progress/ml_reasoning_effort/ml_max_turns/
  paper_export_format/paper_cite_style/paper_tone/kb_embed_model/kb_chunk_size/
  kb_chunk_overlap/exp_template/exp_plot_format/exp_dpi。
- 主题：保留首屏 localStorage 即时上色，但加载后以后端值为准并在切换时同时 PUT。
- 关于 tab 三个按钮按第 3 节接线：backup 走 blob 下载；clear/reset 成功后按需 reload。
- 审批（approval）现有逻辑保持不动。

## 5. 文件归属（并行子任务只允许改自己名下文件，避免冲突）

- **基座**：`matlens_kit/settings_store.py`(新)、`matlens_kit/api/config_api.py`、
  `design/prototype/js/settings.js`。
- **通用+记忆**：`run_agent.py`、`matlens_kit/ui/common.py`、`matlens_kit/api/mem_api.py`、
  以及为生效必须改的 `agent/agent_init.py` / `agent/memory_manager.py` / 图谱自动构建触发处。
- **论文工坊**：`matlens_kit/paper/export.py`、`prompts.py`、`engine.py`、
  `matlens_kit/api/papers_api.py`、`design/prototype/js/paper.js`。
- **知识库**：`matlens_kit/rag/kb.py`、`matlens_kit/plugins/local_rag/__init__.py`、
  `matlens_kit/api/kb_api.py`、`design/prototype/js/kb.js`。
- **实验**：`matlens_kit/api/experiment_api.py`、`matlens_kit/tools/experiment.py`、
  `matlens_kit/tools/plotting.py`、`design/prototype/js/exp.js`。
- **关于+集成（最后）**：`matlens_kit/api/sessions_api.py`、`config_api.py`(追加 backup/reset)、
  新增 `tests/kit/test_settings_*.py`、全量回归。
- **任何人不要改 `matlens_kit/api/server.py`**（所需路由都在已注册路由内新增）。

## 6. 生效验收（关键）

- 每个控件改完→刷新页面值保持（持久化往返）。
- mem-ext 关：发消息不新增 mem0、不召回；mem-auto-write 关：不自动写但保留召回与手动 add；
  mem-graph 关：不触发图谱自动抽取。
- reasoning_effort / max_turns 真正传入 agent（max_turns 限制单轮工具迭代；effort 进请求）。
- papers：默认导出按 export_format；参考文献按 cite_style 改变排版（gb7714/ieee/apa/acs 四式真实不同）；
  tone 进入写作/润色 prompt；autosave 生效。
- kb：改参数后**新建库/新导入**用新 embed_model、chunk_size、chunk_overlap；table_extract 控制
  PDF 表格抽取；root 字段反映真实根目录。
- experiment：新建方案默认 template；绘图输出 plot_format/dpi；autosave 生效。
- 关于：备份可下载 zip；清空会话后列表为空且记忆仍在；重置后设置回默认且需重填 key。
- 不破坏：模型切换/实时目录、审批、聊天 SSE、论文工坊现有流程。
- `.venv\Scripts\python.exe -m pytest tests/kit -q` 全绿。
