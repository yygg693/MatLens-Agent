# MatLens 优化蓝图（总工程师签字版）

> 2026-10-09 总工程师体检后签发。原则：先地基后装修，先闭环后锦上添花。
> 每个分片有明确验收标准，不允许"看起来做完了"。

## 体检结论（事实，不是感觉）

- **不是空架子**：state.db 7.2MB、papers.db 200KB、graph.json 3KB、experiments.db 12KB——真跑过真用过。
- **前端不是草图**：`design/prototype/app.js` 167KB，已有会话/流式/Markdown+KaTeX/工具选择器/@提及/截图，是完整原生 JS 应用。dev-plan 本来就定"零构建 ESM"，方向对。
- **后端不是 stub**：matlens_kit 约 3500 行，9 个 router，paper engine 是完整状态机，材料 16 个工具约 2200 行。
- **硬伤**：
  1. `.venv` 是 Python 3.11，但代码用了 3.12+ f-string 反斜杠语法（已修 1 处，可能还有）。
  2. `start-matlens.bat` 写死的 python 路径（.workbuddy/matlens2）已不存在。
  3. 当前模型配置是 OpenRouter 免费模型 `nvidia/nemotron-3-super-120b:free`——不是 DeepSeek，生成质量/限流都是雷。
  4. 0 个 matlens_kit 自己的测试。
  5. 服务绑 127.0.0.1 裸奔，无鉴权——为上线（营业执照/ICP）做的话这是 P0。
  6. 论文 engine 的 `runner` 是否真接了 AIAgent 流式生成，未端到端验证过。
  7. 前端 167KB 单文件，无错误边界、无 loading/empty/error 三态。
  8. 记忆图谱 graph.json 3KB，前端可视化是否接通未验证。

---

## 分片与验收标准

### S1 工程地基（所有其他分片的前置）
**目标**：让任何人 clone 下来 5 分钟跑起来，且知道改哪里。
- [ ] 全仓扫描 Python 3.11 不兼容语法（f-string 反斜杠、3.12+ 类型语法、`type X =` 语句），逐个修。
- [ ] 重写 `start-matlens.bat` + 新增 `start.ps1`，路径指向 `.venv`，自动检查端口、打印访问地址。
- [ ] 新增 `matlens_kit/README.md`：架构图（FastAPI→routers→paper/rag/tools）、启动命令、目录约定、如何加新 router/新工具。
- [ ] 新增 `tests/kit/` pytest 最小集：
  - `test_health.py`：GET /api/health 200 且 ok=true
  - `test_paper_engine.py`：engine 状态机前置检查、create/list/get/delete
  - `test_paper_db.py`：papers.db CRUD 不串数据
  - `test_material_tools.py`：每个材料工具至少一个 happy-path 调用
- [ ] API 全局异常 handler：所有未捕获异常返回 `{ok:false, error:msg}` 而非 500 堆栈。
- [ ] `pytest tests/kit/ -q` 全绿。

### S2 论文工坊端到端闭环（主推功能，最高业务优先级）
**目标**：从"新建项目"到"导出 Word"走通一遍，断点修掉。
- [ ] 写一个 `scripts/e2e_paper.py`：用 mock LLM runner（不烧 token）跑通 7 步状态机，断言每步落库、前置检查生效、重跑覆盖、错误步骤可恢复。
- [ ] 检查 `papers_api.py` 的 runner 是否真接了 `AIAgent` 流式生成；没接就接上，SSE 事件（stream_text/stage_status/error）前端能收到。
- [ ] 引用白名单强制校验：写一个 `enforce_refs()`，写作步 prompt 注入白名单，quality 步扫描正文 `[n]` 是否都在白名单内，不在就报错。
- [ ] Word 导出（python-docx）：Markdown→.docx，GB/T 7714 参考文献，标题层级正确。
- [ ] 论文→知识库回流：导出后一键把全文切片写入当前激活 KB。
- [ ] 前端论文工坊页面对接：7 步步骤条、每步内容编辑+重跑、SSE 流式显示生成过程。
- [ ] 验收：e2e_paper.py 跑通 + 手动在浏览器走一遍新建→选题→大纲→导出 Word。

### S3 材料工具包（对应用户科研课题：离子液体粘度预测）
**目标**：从"化学计算器集合"升级为"材料科研真正能用的工具包"。
- [ ] 每个工具补 JSON Schema（name/description/parameters/examples），让前端工具目录能展示参数表单。
- [ ] **旗舰工具：`il_viscosity_predict`**——基于用户课题「基于机器学习的离子液体粘度多因素影响机制及预测模型」：
  - 内置一个轻量 GBDT/RF 模型（scikit-learn），训练数据从公开离子液体粘度数据集合成/加载。
  - 输入：阴阳离子类型、温度、压力；输出：粘度预测 + 特征重要性 + 置信区间。
  - 画图：预测 vs 实测散点图（base64 返回前端）。
  - 这是 MatLens 区别于通用 Agent 的招牌。
- [ ] 工具结果可视化：plotting.py 产出的 matplotlib 图统一转 base64 PNG，前端 `<img>` 直接渲染。
- [ ] 每个工具补一个单元测试（S1 里）。

### S4 前端加固（167KB 单文件 → 可维护）
**目标**：不重写，只拆分和补错误边界。
- [ ] app.js 按页面拆成 ESM 模块：`core.js`(fetch/markdown/toast)、`chat.js`、`sessions.js`、`kb.js`、`tools.js`、`paper.js`、`graph.js`、`settings.js`。index.html 用 `<script type="module">` 加载。保持零构建。
- [ ] 全局 `window.onerror` + `unhandledrejection` → toast 提示，不白屏。
- [ ] 所有异步区块加 loading 态（按钮 spinner）、empty 态（"还没有会话，点新建"）、error 态（红色提示+重试按钮）。
- [ ] API 客户端统一：`jget/jpost` 自动处理 401/500/网络错误，不抛 unhandled rejection。
- [ ] 窄屏（<768px）侧边栏折叠成抽屉。
- [ ] 验收：手机浏览器打开布局不破；断网时点按钮不白屏。

### S5 生产化（为上线/商业化做准备）
**目标**：能绑 0.0.0.0 给真实用户用，不裸奔。
- [ ] 鉴权：启动时生成随机 token 打印到控制台；请求头 `Authorization: Bearer <token>` 校验；前端登录页输入一次存 localStorage。
- [ ] 配置项进 `~/.matlens/config.yaml`：`server.host`、`server.port`、`server.auth_token`、`server.allowed_origins`。
- [ ] CORS：生产模式只允许配置的 origin。
- [ ] 备份：启动时自动把 papers.db/state.db 拷到 `~/.matlens/backups/YYYYMMDD/`，保留最近 7 份。
- [ ] 扩展 /api/health：返回 db 大小、agent 是否就绪、最近错误数。
- [ ] Windows 服务化文档：用 `nssm` 或任务计划程序把 python 进程注册为开机自启。

### S6 记忆图谱与 KB
**目标**：蜘蛛网状记忆图真能用。
- [ ] 验证 graph_api.py 的实体抽取真在跑（DeepSeek/OpenRouter 抽材料/方法/性质/参数）。
- [ ] 前端接 vis-network CDN，渲染 graph.json，节点按类型着色（材料=蓝/方法=绿/性质=橙）。
- [ ] 点击节点→高亮关联边→右侧面板显示该实体的来源对话。
- [ ] KB：上传 PDF→切片→入库→检索返回带 source/score，端到端测一遍。

---

## 执行顺序与依赖

```
S1（地基）─────────┬─→ S2（论文闭环，最高业务优先级）
                   ├─→ S3（材料工具，可并行）
                   ├─→ S4（前端加固，可并行）
                   └─→ S5（生产化）
                          S6（记忆图谱）依赖 S1 + S4
```

S1 必须先完。S2/S3/S4 可并行。S5/S6 等前面冒烟通过再上。

## 不做什么（明确划线）
- 不重写前端到 React/Vite——dev-plan 定了零构建原生 JS，保持。
- 不引入新的数据库（SQLite 够用）。
- 不做 Tauri 桌面壳（M8 二期，先把 Web 版做稳）。
- 不动上游 Hermes 核心文件（run_agent.py/cli.py/gateway/），所有定制都在 matlens_kit/ 里。
- 不替用户选模型 provider——当前 OpenRouter 免费模型的局限写进 README，由用户自己决定切 DeepSeek。
