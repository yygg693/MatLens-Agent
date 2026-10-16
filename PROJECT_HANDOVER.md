# MatLens（材料之镜）项目交接文档

> 生成时间：2026-10-14 · 用途：供其他 Agent / 开发者接手继续工作
> 一句话：MatLens 是**材料科研垂直 AI Agent**——FastAPI 后端 + 原生 JS 前端（液体玻璃/果冻 UI）+ SQLite 存储 + DeepSeek 模型，核心功能是**论文工坊**（材料论文全流程生成/导出）与记忆/知识库/聊天。

---

## 1. 项目是什么

- **定位**：材料科研个人 Agent，帮助材料专业用户完成科研全流程（聊天、记忆、知识库、论文撰写）。
- **用户背景**：武汉科技大学材料学院学生（课题：基于机器学习的离子液体粘度多因素影响机制及预测模型研究）。
- **当前核心产品**：**论文工坊**——7 步工作流（选题→检索→大纲→写作→质检→审稿→导出），输出真正排版规范的学术论文（docx/md/tex）。
- **衍生定位**：基于 Hermes Agent 二次开发，品牌为"MatLens / 材料之镜"，未来计划商业化（有 ICP/备案/支付咨询历史）。

---

## 2. 技术架构

### 2.1 总览

```
浏览器 (design/prototype, 原生 JS ESM)
   │  http://127.0.0.1:7896
   ▼
FastAPI (matlens_kit/api/server.py + 10 个模块 router)
   │
   ├── 论文工坊: matlens_kit/paper/* (engine/db/prompts/search/quality/export)
   ├── 记忆: mem_api + Mem0 (chromadb 向量)
   ├── 知识库: kb_api + RAG (Embedder)
   ├── 设置: config_api + settings_store (config.yaml)
   ├── 会话/审批/实验/工具/图谱: sessions/approval/experiment/tools/graph
   ▼
DeepSeek API (api.deepseek.com) —— 唯一生产模型通道
```

### 2.2 关键目录

| 路径 | 内容 |
|---|---|
| `D:\MatLens\matlens_kit\` | **后端核心包** |
| `D:\MatLens\matlens_kit\api\` | FastAPI 路由（server.py 主入口 + 10 模块 router） |
| `D:\MatLens\matlens_kit\paper\` | **论文工坊引擎**（本阶段主战场） |
| `D:\MatLens\matlens_kit\rag\` | RAG 知识库 |
| `D:\MatLens\design\prototype\` | **前端原型**（index.html + js/ 模块） |
| `D:\MatLens\tests\kit\` | 后端测试（test_paper_* 等） |
| `~/.matlens/` | 用户数据目录（.env 密钥、config.yaml 设置、papers.db 论文库） |

### 2.3 数据与配置

- **论文库**：`~/.matlens/papers.db`（SQLite，8 篇论文）
  - 表 `papers(id,title,paper_type,topic,stages_json,created_at,updated_at)`
  - `stages_json = {stage: {status, content, refs, error}}`，7 阶段：topic/search/outline/write/quality/review/export
- **设置**：`~/.matlens/config.yaml`（统一配置，settings_store 读写）
  - papers 段：`cite_style`（gb7714 默认/ieee/apa/acs）、`export_format`（docx 默认/tex/md）、`tone`（formal/concise/detailed）、`autosave`
- **密钥**：`~/.matlens/.env`（仅密钥）：
  - `DEEPSEEK_API_KEY`（**当前有效，实测三个模型均正常**）
  - `OPENROUTER_API_KEY`、`FASTEMBED_CACHE_PATH`

---

## 3. 如何启动

### 3.1 启动服务

```powershell
cd D:\MatLens
.\start.ps1        # 一键启动（含端口占用检测），或手动：
```

```powershell
# 手动启动（注意必须设置环境变量）
Set-Location D:\MatLens
$env:NO_PROXY = "api.deepseek.com,127.0.0.1"
$env:HF_HUB_OFFLINE = "1"
.\.venv\Scripts\python.exe -m matlens_kit.api.server --port 7896
```

- 服务地址：**http://127.0.0.1:7896/**
- Python 解释器：`D:\MatLens\.venv\Scripts\python.exe`（已装 python-docx、mem0ai、chromadb、fastembed、openai、matplotlib 等）
- **改后端 Python 必须重启服务**；只改前端（design/prototype）则浏览器 Ctrl+F5 硬刷新即可

### 3.2 运行测试

```powershell
cd D:\MatLens
.\.venv\Scripts\python.exe -m pytest tests/kit/test_paper_export_docx.py tests/kit/test_paper_quality_academic.py -q
# 全量: .\.venv\Scripts\python.exe -m pytest tests/kit -q
```

### 3.3 环境注意事项

- PowerShell 直接 print 中文有时输出被吞 → 脚本输出写文件再 Read，或设 `$env:PYTHONIOENCODING="utf-8"`
- 本地 HTTP 请求用 `curl.exe --noproxy "*"`（PowerShell 旧版 Invoke-WebRequest 无 -NoProxy 参数且走代理会超时）

---

## 4. 论文工坊（当前主线，重点了解）

### 4.1 7 步工作流（engine.py）

`STAGES = (topic, search, outline, write, quality, review, export)`，前置检查逐步推进，每步产物落库 `stages_json`，可断点续写/单独重跑。

### 4.2 生产链文件（本阶段已完成学术级升级）

| 文件 | 职责 | 状态 |
|---|---|---|
| `paper/engine.py` | 状态机、STAGE_LABELS、前置检查 | 稳定 |
| `paper/db.py` | papers.db 数据层 | 稳定 |
| `paper/prompts.py` | 7 步角色 Prompt + TONE/CITE 注入 | ✅ 学术严谨性重构（12/12 测试过） |
| `paper/search.py` | 双通道检索（本地 RAG + OpenAlex）+ LLM 查询改写 | ✅ 真实检索通道（真实网络 8-16 refs） |
| `paper/refs.py` | 引用风格排版（gb7714/ieee/apa/acs） | ✅ |
| `paper/md_model.py` | write 正文 Markdown 解析（标题/摘要/关键词/章节） | ✅ |
| `paper/export.py` | 导出统一入口（门面） | ✅ 重构（write 为空明确提示） |
| `paper/export_text.py` | md/tex 成稿导出 | ✅ |
| `paper/export_docx.py` | **docx 学术排版导出**（A4/中英文字体/Heading/首行缩进/图件嵌入） | ✅ |
| `paper/enforce_refs.py` | 引用白名单校验（已兼容 `[n]` 与 `{A-n}`） | ✅ 修复占位引用检测 |
| `paper/quality.py` | 学术评审级多维检查（结构/引用/数据/图件/声称一致性等） | ✅ 39 项测试过 |
| `paper/fig_gen.py` | 论文示意图生成（matplotlib） | ✅ 基本可用（2026-10-14 全量回归通过） |
| `paper/guard.py` | **生成结果守卫**：识别上游错误文本（402/401/429 等），落库前拦截 | ✅ 2026-10-14 新增 |
| `paper/quality_gate.py` | **导出质量门**：分数过低/有🔴 问题时导出前警告（不阻断） | ✅ 2026-10-14 新增 |
| `paper/fig_kit.py` | **绘图工具箱**：期刊样式 / Okabe-Ito 色板 / Arrhenius 拟合 / 数值纪律 | ✅ 2026-10-14 新增 |
| `paper/fig_schemes.py` | **数据图谱系**：σ–T / Arrhenius / 密度–收缩率 / I–V / 稳定性 / σ_e–pO₂ / XRD | ✅ 2026-10-14 新增 |
| `paper/fig_eis.py` | **EIS 专业绘图**：Nyquist + Bode + 等效电路拟合（impedance.py） | ✅ 2026-10-14 新增 |
| `paper/data.py`（能力实现在 db/prompts/前端） | **实验数据录入**：proposed/measured 标注 + 表格 + 写作注入 | ✅ **已实现**（见 4.5） |

### 4.3 导出引擎设计（export.py 门面）

- **唯一正文来源**：`write` 阶段 content（经 md_model 解析）
- **完全排除**：topic/search/outline/quality/review 的过程性文字
- **参考文献**：search 阶段 refs，按 settings `papers.cite_style` 排版
- **write 为空**：不导出残文档，返回 `EMPTY_WRITE_MESSAGE` 明确提示

### 4.4 学术严谨性规则（本轮升级核心，prompts/quality 已内置）

1. **数据占位规范**：无真实数据处用"拟议值，待实验确认"，**禁止 `---` 糊弄**
2. **声称克制**：机制用 proposed/consistent with，不用 confirmed/identified（除非有直接证据）
3. **数值自洽**：跨表数据必须自洽（如厚度-ASR 换算、t_ion 与 σ_e 三者关系）
4. **对照设计**：研究论文要求对照样品（如不同掺杂含量、烧结助剂、双层结构）
5. **文献对比表**：Table 需含具体文献、条件、数值，不用裸 "—"
6. **稳定性表述**：100h 只能写 short-term，不得声称 long-term stable
7. **引用白名单**：正文引用必须落在 search refs 白名单内

### 4.5 实验数据录入（已实现，2026-10-14 端到端验证）

用户早已拍板「两者都要」：有真实数据用真的，没有就用拟议 + 如实标注。功能**已完整落地**（此前交接文档误记为"未实现"）。

**数据流全链路**

```
前端 write 步「🧪 实验数据」面板（design/prototype/js/paper.js）
  → POST /api/papers/{pid}/data  （papers_api.py）
  → paper/db.py save_paper_data() → papers.db.experimental_data 列（JSON）
  → 读取：GET /api/papers/{pid} 返回 data 字段
  → 注入：papers_api runner 组ctx["experimental_data"]
        → prompts.data_block() 渲染 → write/outline prompt 的 {experimental_data} 占位符
```

**数据结构**（`~/.matlens/papers.db` → `papers.experimental_data`）

```json
{
  "status": "measured",
  "notes": "2026-10-14 在 SOFC 实验室 EIS 实测，950C，N2 气氛，重复 3 次取均值",
  "tables": [{"name": "Table 1", "caption": "…", "columns": [...], "rows": [...]}],
  "updated_at": "2026-10-14 20:10:33"
}
```

- `status=measured` → prompt 指示「必须填入对应表格并在正文引用，标注测试条件/重复次数/误差」
- `status=proposed` 或未录入 → 指示「须标注拟议值，待实验确认，不得表述为已实测」
- `updated_at` 由服务端权威覆写（前端传值不可信）
- 老库兼容：`_init()` 用 PRAGMA table_info 做幂等 ALTER，已有无该列的老库自动迁移

**UI**（write 步专属）

- 常驻按钮显示状态徽标：`●实测`（绿）/ `●拟议`（黄）
- 展开面板：单选（拟议/实测）+ notes 说明 + 表格 JSON（带「载入模板」）+ 保存
- 已存数据时摘要条常驻：徽标 + notes + 表数 + 更新时间

**验证结果**：`tests/kit/test_paper_data.py` 7 passed；真实浏览器点击全流程通过（`_e2e_data_ui.py`），console 零错误。

### 4.6 生成结果守卫（paper/guard.py，2026-10-14 新增）

**真实事故**：DeepSeek 欠费返回 402时，agent 把错误提示塞进 `final_response`（而非抛异常），runner 视为正常正文落库，**静默覆盖了 20921 字的 v5 正文**。任何欠费/鉴权/限流场景都会中招。

**修复**：`guard.is_error_text()` 识别高置信度错误串（insufficient balance / Incorrect API key / HTTP 4xx-5xx / 余额不足…），`ensure_not_error()` 在落库前抛异常。

**双层接线**（防止个别runner 漏接）

1. `api/papers_api.py` — write 通用runner + search 步分别调 `_guard(final, stage_)`
2. `paper/engine.py` — `run_stage` 内对 runner 返回的 content 再兜底校验一次

**设计取向**：宁可漏判也不误判——只匹配高置信度特征串，长正文里偶现 "HTTP 500" 不误杀（有专门测试）。

**回归**：`tests/kit/test_paper_guard.py` 20 passed，含「错误文本不得覆盖已有正文」与「正常正文不得误伤」两条。

**实测**：修复后重跑 write 步 → `status=error`、`error="[write] 上游模型返回错误而非正文：HTTP 402：…"`、正文 20921 字完好。

### 4.7 导出质量门（paper/quality_gate.py，2026-10-14 新增）

导出前若质量不达标，**警告但不阻断**——学术写作场景下用户有权决定是否导出，硬阻断会在「先导出看看」这类正常操作上制造障碍。

**触发条件**（两条任一）

1. `check_quality()` 分数 <阈值（默认 60，settings `papers.export_min_score`）
2. 存在 🔴 严重问题

**放行条件**：`quality` 步未跑过（`status != done`）→ **无据不判，直接放行**；正文为空 → 放行（由 EMPTY_WRITE_MESSAGE 另行处理）；`check_quality` 抛异常 → 放行（门是辅助，不是关卡）。

**接线**

| 层 | 位置 | 行为 |
|---|---|---|
| 门 | `paper/quality_gate.py` `evaluate()` | 纯本地计算，不调模型/网络 |
| 门面 | `paper/export.py` `export_paper(..., force=False)` | 返回值加 `warning` + `quality_gate` 字段，**不拦下载** |
| API | `GET /api/papers/{pid}/quality_gate` | 前端预检端点 |
| API | `GET /api/papers/{pid}/export/{fmt}?force=true` | 跳门参数 |
| API | `X-Matlens-Quality-Warning` 响应头 | 警告文本（URL 编码）透出 |
| 前端 | `js/paper.js exportPaper(fmt, force)` | 预检→ 不达标则 `confirm()` 二次确认 → 带 force 重发 |

**settings 新增**：`papers.export_quality_gate`（bool，默认 true）、`papers.export_min_score`（int，默认 60）

**回归**：`tests/kit/test_paper_quality_gate.py` 13 passed，含「警告但不阻断」「force 抑制」「门异常不挡导出」。

**实测**：v6 论文（55 分）→ 预检返回 `passed=false, reasons=["质量评分 55/100 低于阈值 60"]`，加 `?force=true` 后正常导出 docx。

### 4.8 丢图检测（2026-10-14 新增，v6 实测发现）

**真事故**：v6 生成时模型把该画图的数据**全改写成表格**（7 张表），正文有 12 处「图 N」交叉引用但**零图注行** → `export_docx` 靠 `**图 N**` 定位插图，找不到就**静默丢图**（v5 内嵌 2 张图，v6 有 0 张）。

**两处修复**

1. `paper/prompts.py` 规则 R —— 明确图注格式是硬要求（`**图 N** <说明>` 独立行），并明令「不得把图改写成表来规避图注要求」
2. `paper/quality.py` `_figure_missing_issues()` —— 新增模式 2：篇幅 >3000 字 + ≥3 处表格引用 + **零图注行** → 报丢图

**关键判据**：模式 2 用「图注行 `**图 N**`」而非任意「图 N」字样——正文里"见表 7""如图 3 所示"这类交叉引用不代表规划了图（v6 实测：图 N 引用 12 处、图注行 0 处）。

**回归**：`tests/kit/test_paper_figure_guard.py` 7 passed，含「有图注不误伤 v5」「交叉引用不算图注」两条关键断言。

**已知遗留**：`fig_gen` 只对 `kind=cell/mechanism` 的图注作画（data/unknown 跳过——无真实数据不画，防用拟议数据造假图，这是**刻意设计**）。v7 的 8 张图注只有 1 张命中 `cell`，故实得 1 张图。判定图是否够用应看**图注数**而非 PNG 数。

**图件目录约定（2026-10-14 打通）**：`~/.matlens/papers/<pid>/figures/fig_{n}_*.png`
- `export.figures_dir_for(p)` 定位/按需创建该目录，**已接进 `export_paper` 的 docx 分支**
- 之前 `export_docx(figures_dir=...)` 参数从未被 API 层传入 → 走API 导出永远无图（v5 的 2 张图是当时手动传目录插的，原PNG 已不在磁盘）
- 现在链路：`fig_gen.gen_figures(content, figures_dir_for(p))` → 导出自动插图

---

### 4.9 科研绘图链（fig_kit / fig_schemes / fig_eis，2026-10-14 新增）

**为什么不用 AI 生图**：DeepSeek V4 全系（含V4-Pro）**没有图像生成端点**；即使有也不能用于科研数据图——数据图必须数值可复现，扩散模型画的谱图是像素插值、无数据溯源，等同造假。正确形态是**代码绘图 + 专业算法库**。

**三级能力**

| 级 | 内容 | 状态 |
|---|---|---|
| 一级 | 7 种数据图谱系，从 `experimental_data.tables` 取数 | ✅ |
| 二级 | EIS 专业库（impedance.py 1.7.1）：Nyquist/Bode + 等效电路拟合 | ✅ |
| 三级 | LLM 驱动 Agent + VLM 视觉自检（CoDA 式四阶段） | ⏸ 未做（需VLM，DeepSeek 只能承担代码生成半边） |

**一级：7 种谱系**

| 谱系 | 图型 | 判据关键词 | 产出指标 |
|---|---|---|---|
| `sigma_t` | σ vs T 多组分对照 | 电导率随温度 | 组分数 |
| `arrhenius` | ln(σT) vs 1000/T | Arrhenius / Ea / 1000/T | **Ea(eV) + R²** |
| `density_shrink` | 烧结温度–密度/收缩率双面板 | 收缩率 / 相对密度 | 组分数 |
| `iv_ip` | I–V + I–P 双面板 | I–V / 功率密度 / OCV | **峰值功率密度** |
| `stability` | 电压–时间 + 衰减率 | 恒流 / 稳定性 / 衰减 | **衰减率 %/(100h)** |
| `po2_sigmae` | σ_e–pO₂ log–log + 1/4 斜率参考 | pO₂ / Hebb-Wagner | **拟合斜率** |
| `xrd` | XRD 全谱叠放 | XRD / 衍射 / Rietveld | 谱数 |
| `eis` | Nyquist + Bode 双面板 + 拟合 | Nyquist / EIS | **等效电路参数** |

**二级：EIS（`impedance.py` 1.7.1，ECS Hack Week 起源的社区标准库）**

- 三档等效电路候选，自动选残差最小者：
  - `R0-p(R1,CPE_1)-p(R2,CPE_2)`（SOFC 双弧标准模型）
  - `R0-p(R1,CPE_1)`（单弧）
  - `R0-R1-R2`（退化）
- 拟合实测精度（合成 R0=0.12、双 RC、n=0.85 数据）：`R0=0.11998`、`CPE exponent=0.8483`、残差 **0.0003**
- ⚠️ **impedance 1.7.x API 踩坑记录**：
  - `CustomCircuit` 元件语法是 `R0-p(R1,CPE_1)`（串联 `-`、并联 `-p(...)`），**不是** 逗号分隔
  - 参数名用 `get_param_names()` 方法，且它返回**元组** `(names, units)` —— 直接 `list()` 会得到嵌套列表导致参数全空
  - `parameters_` 在 `fit()` 前是 `None`
  - 绘图模块是 `impedance.visualization`（**不是** `impedance.plotting`，后者在 1.7 已移除）
- **降级语义**：库缺失/失败 → 退回纯散点图并如实标注 `library="matplotlib (impedance.py 不可用)"`

**学术诚信红线（fig_kit 的硬约束）**

- `RefuseToDraw` 异常是**正常业务分支**：数据不足就跳过该图，绝不臆造数值画"看起来像实验结果"的图
- `assert_no_fabrication()`：绘图值必须能在录入数据里找到出处，否则拒绝出图（防图-文不一致）
- 每个 skipped 都带**具体 reason**（前端要能告诉用户为什么没图），如"谱系 'sigma_t' 需真实实验数据：请在「实验数据」中录入数据表"
- 期刊样式硬性：字号 ≥8pt、Okabe-Ito 色盲色板（禁 Matplotlib 默认蓝 `#1f77b4`）、轴标签英文（中文会渲染成豆腐块）、上下标降级为ASCII
- 每张图输出 **PNG(300dpi) + PDF + SVG** 三格式

**接线**

| 层 | 位置 | 行为 |
|---|---|---|
| API | `POST /api/papers/{pid}/figures` | 生成图件，返回逐图结果（含 skipped reason） |
| API | `GET /api/papers/{pid}/figures` | 列出已生成图件 |
| API | `GET /api/papers/{pid}/figures/file/{name}` | 回传图件（basename 防目录穿越） |
| 门面 | `export.export_paper(docx)` | **导出前自动补图**，失败不阻断导出 |
| 目录 | `~/.matlens/papers/<pid>/figures/fig_{n}_{scheme}.{png,pdf,svg}` | 约定目录（`figures_dir_for()`） |

**实测**：v7 论文（8 图注、1 张示意图、2 张实测表）→ 生成 3 张（Arrhenius Ea=1.536 eV R²=0.984、cell 示意图、稳定性衰减 1.4963%/(100h)），5 张明确 skipped 并各带原因。

**依赖**：`requirements.txt` 新增 `impedance>=1.7,<2`（可选，缺失时降级不崩）。⚠️ 清华镜像对该包 **403**，需 `pip install -i https://pypi.org/simple impedance`。

**回归**：`test_paper_fig_schemes.py` 34 passed + `test_paper_fig_eis.py` 15 passed。

**踩坑记录：多表误聚合**

`σ–T` / Arrhenius 图要把"所有组分的表"聚合到一张图，若不做物理约束会把 σ_e–pO₂ 表误拉进来（`pO₂` 列名含 `t` 被当温度列，且 `1e-25~1e-18` 跨度 1e-18 骗过"逐值落在区间内"的检查，凭空多出一条 Ea≈0 的假曲线）。四重约束：跨度 1~2500、起点 |min|≤2000、单调递增/减、相邻间距比<100。

---

## 5. 已完成工作（历史里程碑）

| 阶段 | 内容 | 状态 |
|---|---|---|
| 记忆修复 | 漏装 mem0ai/chromadb/fastembed → 补齐，同步错误/记忆图谱恢复 | ✅ |
| 导出中文文件名 | latin-1 编码报错 → urllib.parse.quote() 修复 | ✅ |
| 聊天体验 | 立即"思考中"占位、生成中停止按钮 | ✅ |
| 设置页重构 | 模态弹窗、分层导航、provider 卡片编辑、模型实时拉取、液体玻璃+果冻材质统一 | ✅ |
| 设置全链路接通 | 8 个 tab 全部接后端 config.yaml，89 项测试通过 | ✅ |
| 导出引擎重构 | 以 write 正文为唯一来源，docx 学术排版 | ✅ |
| **生产链学术升级** | prompts/search/quality/enforce_refs/export_docx 全面升级 | ✅ |
| v5 论文交付 | 30 处定点修订，17 页带 2 图，quality 48→48 分 | ✅ |
| **实验数据录入** | proposed/measured 标注 + 表格 + 写作注入，前后端 + E2E 验证 | ✅（4.5） |
| **生成结果守卫** | 上游错误文本不再覆盖正文（402 事故修复） | ✅（4.6） |
| **导出质量门** | 分数过低/🔴 问题导出前警告（不阻断）+ force 跳过 | ✅（4.7） |
| **丢图检测** | 零图注即告警 + prompts 强制图注格式 | ✅（4.8） |
| **图件链路打通** | `figures_dir_for()` 约定目录，导出自动插图 | ✅（4.8） |
| **科研绘图链一级** | 7 种数据图谱系，从录入数据取数，无数据拒绝出图 | ✅（4.9） |
| **科研绘图链二级** | impedance.py 接入：Nyquist+Bode+等效电路拟合 | ✅（4.9） |
| **v7 论文交付** | 8 图注 + 11 表 + 实测电导率表，quality 50，🔴 已清零 | ✅（本轮） |

---

## 6. 当前状态与待办

### 6.1 进行中：论文工坊评审闭环

- **已交付**：`D:\MatLens\论文导出示例_SOFC电解质_v5.docx`（17 页）+ `D:\MatLens\论文导出示例_SOFC电解质_v5.md`（评审用全文，20921 字符）
- **等待用户**：把 v5.md 贴入 **DeepSeek 网页版** 评审，拿回意见 → 继续迭代
- **当前论文性质**：拟议数据设计稿（全文零实测数据，按红线如实标注"拟议值，待实验确认"）——这是用户确认的诚信红线，非工坊缺陷
- **v5 残留**：quality 48 分（非 100），数值自洽、图件、表述克制已到生产链上限；提分需录入真实实验数据
- **✅ 已解除**：「实验数据录入/导入」已实现并端到端验证（见 4.5）
- **v6/v7 交付（2026-10-14）**：录入 LSM-LSCF 集流层实测电导率（EIS，N₂，950 °C，重复 3 次：800/850/900 °C → 0.12/0.28/0.45 S·cm⁻¹）后重跑写作
  - **v6**（27074→28711 字符）：实测数据进正文 7/7 命中，但**零图注→ 导出丢图（0 张）**
  - **v7**（27074 字符 / 11 表 / 8 图注 / 1 图）：修prompt + 检测后重跑，图注恢复，**最终交付版本**
  - 交付物：`论文导出示例_SOFC电解质_v7.docx`（126KB，含表 9 实测电导率）+ `_v7.md`
  - 质量分 48 → 50，🔴 严重问题清零；残留全为 🟡（拟议数据设计稿的固有属性）
  - 备份：`_backup_20261014/`（v5 docx+md、重写前 stages 快照）
- **注意**：`quality` 分数随 refs 落库状态会小幅波动（v6 落库时 55、离线重算 50），横向对比须用同一 refs 快照

### 6.2 服务状态

- **服务运行中**（监听 PID 用 `netstat -ano | findstr 7896` 查），已加载全部 2026-10-14 改动
- 停止：`taskkill /PID <pid> /F`（⚠️ Git Bash 下 `pkill -f matlens_kit` **杀不掉**该进程，必须用 taskkill 按 PID）
- ⚠️ 端口被占用时新进程会 bind 失败并立即退出（`[Errno 10048]`），但健康检查仍会通过**旧进程** → 改后端后务必确认监听 PID 已换新
- ⚠️ **`nohup ... &` 起的服务会随shell 退出被回收**（曾导致 502/服务消失）→ 用工具的后台任务方式启动，不要用 `nohup`

### 6.3 已知问题/边界

1. **绘图链三级（LLM Agent + VLM 视觉自检）未做** —— CoDA 式四阶段架构，需 VLM；DeepSeek 只能承担"代码生成"半边，视觉自检要另接 GPT-4V/Gemini。当前一/二级对固定谱系够用
2. `fig_eis` 只画 Nyquist/Bode；`SEM` / `STEM-EDS` / `XPS` / `TGA` / `DRT` 图**未实现**（DRT 需 DRTtools，SEM 需真实显微图）
3. 切换嵌入模型后旧知识库维度不自动迁移（需删库重建）
4. 论文导出若 write 为空 → 明确提示，不导出残文档（设计如此）
5. quality 分数随 refs 状态波动，横向对比须固定 refs 快照
6. 图注若写得太笼统（如"结果见图"）→ 无法识别谱系 → skipped 并提示
7. 全量回归 **295 passed / 0 failed**（2026-10-14，`pytest tests/kit -q`）

### 6.4 待办建议（供接手 Agent 参考）

- [ ] 等 DeepSeek 网页版对 `_v7.md` 的评审意见 → 对照迭代
- [ ] 补齐真实实验数据（XRD/EIS/SEM/DRT）→ 把 data 从 measured 部分扩展到全篇，冲 quality 60+ 门槛（当前 50）
- [ ] 前端加「生成图件」按钮 + 图件预览网格（后端端点已通，前端未接）
- [ ] 设置页 UI 补 `export_quality_gate` / `export_min_score` 两个开关（后端已通，前端未接）
- [ ] 补 DRT 图（DRTtools）与 SEM 拼图支持
- [ ] 绘图链三级：LLM 生成代码 + VLM 视觉自检闭环
- [ ] 根目录 `_*.py` / `_*.log` / `_fig_test/` 清理（均为可复现验证脚本与产物，可留可清）

### 6.5 ⚠️ 前端死代码清理（2026-10-15 发现，**未处理**）

**`design/prototype/app.js` 共 2950 行从未被浏览器加载** —— `index.html` 里
**没有 `<script src="app.js">` 标签**，实测浏览器请求列表只有 18 个 ES 模块，
`window.sendMsg` / `window.renderModeBadge` / `window.bindChipPanels` 全是
`undefined`。它的 133 个函数（`loadSessions`/`selectSession`/`openToolCatalog`/
`uploadAttachment`…）在 `js/*.js` 里都有同名同实现版本——**说明它已被成功模块化，
模块是它的进化版**。

**真正覆盖模块的是 `index.html` 第 1850–2043 行的 193 行内联脚本**：
- Enter 发送、自动增高、发送/停止按钮绑定（与 `chat.js` 重复）
- 自带一份 12 条硬编码 `tools` 数组（与 `/api/tools` 的 23+ 条重复）
- 右栏 tab 切换（2026-10-15 已删，其余仍在）

**处理建议**（分两步，勿混做）：
1. 确认 `app.js` 无独有逻辑后删除该文件（留 `.bak`）
2. 把内联脚本 193 行收进 `js/` 模块，删除内联 `<script>` 块

⚠️ 注意：本轮修bug 时曾误把「改动不生效」归因于 app.js 覆盖，实际是内联脚本。
**改动前端后必须真跑浏览器验证**，`node --check` 对 ESM 无效。

---

## 7. 关键 API 速查

### 7.1 路由注册（server.py）

```python
app.include_router(_sessions_router)   # 会话
app.include_router(_kb_router)         # 知识库
app.include_router(_mem_router)        # 记忆
app.include_router(_graph_router)      # 记忆图谱
app.include_router(_config_router)     # 设置（含模型 catalog）
app.include_router(_approval_router)   # 审批
app.include_router(_papers_router)     # 论文工坊
app.include_router(_experiment_router) # 实验
app.include_router(_tools_router)      # 工具
```

### 7.2 论文工坊端点（papers_api.py）

- 论文 CRUD：`/api/papers`（GET/POST）、`/api/papers/{pid}`（GET/PUT/DELETE）
- 阶段执行：`/api/papers/{pid}/run/{stage}`（SSE 流式，emit stage_status/stream_text/done/error）
- 手动保存：`/api/papers/{pid}/stage/{stage}`（PUT content/refs）
- 导出：`/api/papers/{pid}/export?fmt=docx|md|tex&cite_style=...&force=true`（中文文件名已 URL 编码）
- 实验数据：`POST /api/papers/{pid}/data`（proposed/measured 标注）
- **图件**：`POST /api/papers/{pid}/figures`（生成）、`GET .../figures`（列表）、`GET .../figures/file/{name}`（回传）
- 质量门：`GET /api/papers/{pid}/quality_gate`（导出预检）

### 7.3 设置端点（config_api.py）

- `/api/settings`（GET 全量/PUT 保存）
- 模型 catalog：`/api/settings/catalog?provider=deepseek`（**必须传 provider**，实时拉模型，DeepSeek 直连约 400ms；OpenRouter 全量 469 模型约 1764ms 故不全拉）

---

## 8. DeepSeek 模型通道（2026-10 实测）

- Base URL：`https://api.deepseek.com/v1`
- `/v1/models` 实时返回 2 个 id：`deepseek-flash`（友好名 DeepSeek-V4.1-Flash，1M 上下文）、`deepseek-v4-pro`（友好名 DeepSeek-V4-Pro）
- `deepseek-chat` 是别名，不在 /models 列表但可用
- **生产链全程只准 DeepSeek**（用户硬指令：其他模型不好用，严禁偷偷换 openrouter/stepfun）
- 论文工坊端到端重跑用 `deepseek-v4-flash`
- **2026-10-14 20:38 已充值验证恢复**（HTTP 200 + usage 正常计费）。此前欠费期（402）曾**静默覆盖正文**，现已由 `paper/guard.py` 拦截，见 4.6

---

## 9. 给接手 Agent 的提醒

1. **用户偏好**：只看最终结果、要实质交付物（docx 样本、评审对照结论），讨厌"看起来完整其实没做完"
2. **用户授权**：可多开 Agent、不省 token、不计时间，但**改动必须验证**（真实导出→渲染截图肉眼确认）
3. **学术诚信红线**：AI 生成数据必须标"拟议值，待实验确认"，绝不冒充真实实验数据
4. **UI 材质**：液体玻璃 + 果冻 Q 弹 + 光效是项目标志风格，新界面必须统一
5. **改动后端必须重启 7896 服务**；只改前端硬刷新即可
   - ⚠️ 重启必须 `taskkill /PID`（Git Bash 的 `pkill -f` 对该进程无效）
   - ⚠️ 改完后**确认监听 PID 已换新**——旧进程占着端口时，新进程静默 bind 失败退出，健康检查却照样通过，你会误以为改动已生效
6. **不要拿"测试通过"当验证终点**：2026-10-14 这次实验数据录入功能，单测 7 passed、UI 点击零报错，全绿——但一调真实生成就撞上 402，而**这个 402 顺带把2 万字正文覆盖了**。必须跑到真实链路
7. **测试别打真实库**：`PaperEngine` 内部走 `PDB` 模块级默认路径，测试里必须 `monkeypatch.setattr(PDB, "_PAPER_DB", tmp)`，否则会污染 `~/.matlens/papers.db`
8. 项目根目录有多个 `_*.py`/`_*.log`/`_*.txt` 临时文件，是排查/验证过程产物，可清理但注意先确认无引用
