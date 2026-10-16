# MatLens Agent 工作台 · 开发计划

> 状态：已确认（2026-08-23），老板拍板后执行。先 Web 后桌面。

## 技术选型
| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | FastAPI（已有）+ SSE 事件流 | 事件流天然适合 SSE 单向推送；审批回传用 REST POST |
| 前端 | 原生 JS（ESM 模块化）单页应用，零构建链 | 延续 MatLens 零构建原则 |
| 图谱 | vis-network（CDN 力导向图） | 蜘蛛网记忆图，无构建引入 |
| 桌面壳 | Tauri 2（二期） | Web 做稳后再包壳 |

## 里程碑
- **M0** 服务层与事件流协议：FastAPI + 会话存储（state.db）+ SSE 七类事件（thinking/tool_call/tool_result/approval_request/stream_text/done/error）+ 前端骨架
- **M1** 三栏事件流对话：会话列表（多会话/分支/恢复）+ 事件流（思考折叠/工具卡/引用角标/流式）+ 停止生成 + 右侧上下文面板
- **M2** 审批体系（Codex 式）：工具级 allow/prompt/block 规则 + untrusted/on-request/never 策略；默认代码执行/写文件/删除/浏览器需审批；审批卡片 UI
- **M3** 工具中心：Hermes 32 通用 + 材料 12 全展示，分类（通用/材料计算/实验/数据/写作/浏览器），独立参数表单
- **M4** 知识库 + 引用：管理/批量上传（PDF/TXT/CSV/Excel）/重建索引；引用角标→悬停→跳知识库
- **M5** 记忆图谱面板（蜘蛛网）：DeepSeek 从 Mem0 记忆条目抽实体（材料/方法/性质/参数/人）+ 关系；NetworkX → ~/.matlens/graph.json 增量更新；vis-network 力导向图；记忆按 [用户]/[实验]/[材料]/[结论] 过滤/编辑/删除
- **M6** 论文工坊：7 步（选题→检索→大纲→写作→质量巡检→审稿→导出 Word/LaTeX/Markdown），每步独立面板可回退重跑；参考老项目 mra/pipeline/paper_workflow.py 的 stage 落库模式，交互重新设计
- **M7** 设置 + 打磨：模型/记忆/知识库参数/UI 主题/安全
- **M8** 桌面壳（Tauri 2）：内嵌 Web，同一后端

## 左侧栏结构（7 项）
💬 对话 / 📚 知识库 / 🧰 工具中心 / 🧫 实验 / 📄 论文工坊 / 🧠 记忆图谱 / ⚙️ 设置

## 关键决策（老板拍板）
1. 事件流为主（Codex 式），非纯聊天
2. 轻量前端（原生 JS + FastAPI）
3. 审批设计参考 Codex（ExecPolicy + ApprovalPolicy）
4. 记忆面板蜘蛛网状（Mem0 之上叠加轻量知识图谱，实体抽取+力导向图）
5. Agent 工具不减少（Hermes 32 + 材料 12 全保留）
6. 论文工坊参考老项目 7 步流程重新设计
