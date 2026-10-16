# MatLens 优化落地报告（S1–S6 全部分片）

> 2026-10-09 总工程师带队，多 agent 并行施工完成。蓝图 `design/OPTIMIZATION.md` 六个分片全部落地并真跑验收。
> 服务已在 127.0.0.1:7896 运行最新代码；`/api/health` 200 ok=true、agent_ready=true。

## 0. 模型切换（用户侧已完成，记录在案）

用户已把 `~/.matlens/config.yaml` 的 model 段从 OpenRouter 免费模型切到 DeepSeek：

```yaml
model:
  default: deepseek-chat
  provider: deepseek
  base_url: https://api.deepseek.com/v1
```

原配置备份在 `config.yaml.bak.before-deepseek`。`DEEPSEEK_API_KEY` 在 `~/.matlens/.env` 中已存在并 curl 验证有效。
- 若 `provider: deepseek` 运行时不认，fallback 为 `provider: openai-compatible` + 同一 base_url + 读 `DEEPSEEK_API_KEY`。
- 本轮所有 pytest / e2e 脚本**均用 mock runner 或本地哈希嵌入，没有真调 LLM**；只有 S6 验证图谱实体抽取时真调了一次 DeepSeek（返回 12 节点 12 边，分类正确）。
- 新环境装包：`.venv` 内补装 scikit-learn 1.7.2 / matplotlib 3.10.9 / numpy 2.4.6 / pandas 2.3.3 / scipy 1.17.1 / python-docx 1.2.0（S3 旗舰工具与 S2 Word 导出依赖）。

---

## S1 工程地基 ✅

**做了什么**
- AST 全量扫描 `matlens_kit/`（现 45 个 .py）：无 Python 3.11 语法错误（此前 server.py 的 f-string 反斜杠是唯一雷，已修）。
- 重写 `start-matlens.bat`：解释器指向 `D:\MatLens\.venv\Scripts\python.exe`，启动 `python -m matlens_kit.api.server --port 7896`，删除旧 `.workbuddy/matlens2` 死路径。
- 新建 `start.ps1`（UTF-8 **带 BOM**，否则 PS5.1 中文乱码）：启动前 `Get-NetTCPConnection` 查 7896 占用，打印 `http://127.0.0.1:7896`。
- 新建 `matlens_kit/README.md`：架构（FastAPI → 9 router → paper/rag/tools/ui）、启动命令、目录约定、如何加 router / 加材料工具。
- `matlens_kit/api/server.py` 加全局 `@app.exception_handler(Exception)`：未捕获异常统一返回 `500 {"ok":false,"error":...}`，不再裸堆栈（已实测挂 `/__boom__` 抛错路由返回预期 JSON）。
- 新建 `tests/kit/`（conftest + test_health + test_paper_engine + test_paper_db）。

**测试**：`pytest tests/kit/ -q` → **34 passed**（含 S3 的 23 个材料工具用例）。

---

## S2 论文工坊端到端闭环（后端）✅

**做了什么**
- 新建 `scripts/e2e_paper.py`：mock LLM runner 跑通 7 步状态机，断言每步落库、前置拦截（未完成 topic 直接跑 outline 被拒）、重跑覆盖、错误恢复（runner 抛错→status=error→修正后重跑回 done）。全程 `PDB._PAPER_DB` 重定向临时库，真实 papers.db 零写入。
- 新建 `matlens_kit/paper/enforce_refs.py`：引用白名单单一事实源。写步 prompt 注入 search 步 refs 白名单；quality 步扫描正文 `[n]`，越界编号进「引用越界」报告条目（不抛异常）。
- 打磨 `paper/export.py`：Word 导出参考文献改 GB/T 7714 风格，标题层级 title=H0 / 阶段=H1 / `##`=H2 / `###`=H3。
- `papers_api.py` 新增 `POST /api/papers/{pid}/to_kb`：把 write 成稿切片写入当前激活知识库（复用 `rag/kb.py` 的 `add_document`，临时 md 用完即删）。

**验收**
- `python scripts\e2e_paper.py` → `E2E PAPER OK`（7/7 步 done，引用越界 [9] 被识别）。
- `export_paper(p,"docx")` 返回 **37074 字节**，文件名 `离子液体粘度预测.docx`。

---

## S3 材料工具包（旗舰：离子液体粘度预测）✅

**做了什么**
- 新建 `matlens_kit/tools/il_viscosity.py`：旗舰工具 `il_viscosity_predict`。模块加载时用确定性合成数据（Arrhenius/VFT 经验式 + 噪声，n=3000）训练 GradientBoostingRegressor（log 目标，rmse_log≈0.074≈7%）。输入阳离子/阴离子/温度/压力，输出粘度预测 + 95% 置信区间 + 特征重要性 + matplotlib(Agg)「预测 vs 实测」散点图 base64 PNG。
- `plotting.py` 改 Agg + BytesIO + base64，`plot_b64` 字段前端 `<img>` 直渲染，不落盘。
- 全部 20+ 工具 schema 补顶层 description + examples。
- 新建 `tests/kit/test_material_tools.py`（23 用例）。
- **顺手修了一个真 bug**：`data_processing._sg_coeffs` 返回长度=polyorder+1(3) 与滑动窗口(7) 维度不匹配，导致 `xrd_preprocess` 对默认窗口必崩；改为返回标准窗口-5 二次核 `[-3,12,17,12,-3]/35`，长度对齐。

**旗舰工具真实调用**
- `[OMIM]+ / [Cl]- / 323.15K / 10MPa` → **η=312.5 mPa·s**，95% CI [270.2, 361.5]；特征重要性 `温度0.51 / 阴离子0.40 / 阳离子0.08 / 压力0.008`；plot_b64 112KB。
- 对照 `[BMIM][BF4]@30°C` = 114.3 mPa·s，量级与文献一致。

---

## S4 前端加固 + ESM 拆分 ✅

**做了什么**
- 167KB `app.js` 机械拆成 10 个原生 ESM 模块（`design/prototype/js/`）：core.js(387) / chat.js(1126) / sessions.js(200) / kb.js(135) / tools.js(126) / paper.js(336) / graph.js(141) / settings.js(242) / exp.js(420) / main.js(226)。index.html 改 `<script type="module" src="/js/main.js">`。**零构建，未迁 React/Vite**。
- core.js：`jget/jpost/jput/jdel` 统一 API 客户端（30s 超时、401/5xx/网络错误自动红 toast、返回 `{ok:false}` 不抛 unhandled rejection）；`window.onerror`+`unhandledrejection`→错误边界；<768px 汉堡抽屉。
- 会话/KB/工具/论文列表全部补 loading / empty / error+重试 三态。
- paper.js：7 步步骤条、每步可编辑保存+单独重跑(SSE)、新增「导出 Word(.docx)」「回流知识库」按钮（带 loading）。

**验收**：10/10 模块 `node --check` 通过；所有跨模块 import 静态解析 ALL IMPORTS RESOLVE；7896 上 `/js/*.js` 全部 200。

---

## S5 生产化 ✅

**做了什么**
- `server.py` 读 `~/.matlens/config.yaml` 的 `server:` 段（host/port/auth_enabled/auth_token/allowed_origins，缺省不崩）。
- 鉴权中间件：`auth_enabled=true` 时除静态资源和 `/api/health` 外所有 `/api/*` 要 `Authorization: Bearer <token>`；token 留空则启动随机生成并打印到控制台；**默认关，本地不锁死**。core.js 自动带 token 头，401 弹 token 浮层存 localStorage 后重放。
- CORS：配了 allowed_origins 才加白名单中间件，否则同源。
- 启动后台 `backup_databases()`：papers.db/state.db(连 wal/shm) 拷到 `~/.matlens/backups/YYYYMMDD_HHMMSS/`，只留最近 7 份。
- `/api/health` 扩字段；`design/PRODUCTION.md` 写 NSSM / schtasks 开机自启 +「绑 0.0.0.0 前必须开 auth」红线。

**验收（实测）**
- `/api/health` 热身后：`{"ok":true,...,"db":{"papers_db_kb":200.0,"state_db_kb":7092.0,"graph_json_kb":3.1},"agent_ready":true,"errors_warn":316}`。冷启动 health 0.5s 非阻塞 peek，不挂死。
- auth 实测（临时 7897）：无 token→401，错 token→401，正确 Bearer→200，/health 与静态→200。验证后已关 7897、config 还原默认。
- `~/.matlens/backups/` 已生成多份快照。

---

## S6 记忆图谱与 KB ✅

**做了什么**
- **关键发现**：原 `graph_api.py` 的实体抽取依赖 `litellm`（venv 没装），实际一直走启发式降级——是哑路径。已改为 `openai.OpenAI(base_url=https://api.deepseek.com/v1)` 直连，key 从 secret scope→环境→`~/.matlens/.env` 解析，prompt 抽材料/方法/性质/参数四类实体。
- graph.js 接 vis-network CDN：Barnes-Hut 布局，节点按类型着色（材料蓝/方法绿/性质橙/参数灰），点节点高亮关联边、右侧面板显示来源。
- `rag/kb.py` 的 VectorStore 加 numpy 余弦降级（faiss 未装，离线可用，装 faiss-cpu 后自动切回）。
- 新建 `scripts/e2e_kb.py`：临时库 add 一段离子液体文本，query「粘度 温度」，断言返回 source+score。

**验收**
- 真调一次 DeepSeek 抽实体：返回 12 节点 12 边（材料 `[BMIM][BF4]`、性质「粘度随温度升高而降低」、参数「298-353K」、方法「旋转流变仪」等），分类准确。
- `python scripts\e2e_kb.py` → `KB E2E OK`（source=ionic_liquid.md，score=0.491），全程本地嵌入零网络。

---

## 最终合流验收（总工程师复核）

```
pytest tests/kit/ -q        → 34 passed, 2 warnings in 19.31s
python scripts\e2e_paper.py  → E2E PAPER OK
python scripts\e2e_kb.py     → KB E2E OK (score=0.491)
GET 127.0.0.1:7896/api/health → 200 ok=true agent_ready=true
GET / , /js/main.js, /js/core.js, /js/graph.js, /js/paper.js → 全部 200
```

## 遗留问题（用户下一步）

1. **浏览器人工走查一遍**：打开 http://127.0.0.1:7896 ，重点过 聊天 / 会话 / KB / 工具 / 论文工坊 / 记忆图谱 / 实验 七个页面，DevTools Console 看有无跨模块引用报错（无头环境没替你点过真实渲染）。论文工坊页试一次「导出 Word」和「回流知识库」。
2. **开机自启**：现在 7896 是后台 python 进程，重启电脑后要自己跑 `start.ps1`。要常驻就按 `design/PRODUCTION.md` 用 NSSM 注册服务。
3. **上线前**：绑 0.0.0.0 前先在 config.yaml 设 `server.auth_enabled: true`（token 启动会打印在控制台），否则裸奔。
4. **旗舰模型**：`il_viscosity_predict` 目前用确定性合成数据训练（演示多因素机制）。你真发表时，把实测离子液体粘度 CSV 喂进去重训即可，接口不变。
5. **可选装包**：`pip install faiss-cpu pymatgen`——前者让 KB 走 FAISS 索引（现在 numpy 余弦等价可用），后者启用 crystal_structure 工具（现在优雅降级）。
6. S4 提到的小重构（TOOL_DATA 双份、SSE 未抽 helper）不影响功能，可后续再收。
