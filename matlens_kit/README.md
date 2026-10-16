# MatLens Kit（材料之镜）

MatLens 是一个面向材料科研的 Web 工作台，基于 Hermes Agent 二次开发。
`matlens_kit/` 是全部**定制代码**所在：在 Hermes 核心之上包一层 FastAPI HTTP 服务、
一套论文写作状态机、本地知识库（RAG）和一组离线材料计算工具。

> 上游 Hermes 核心文件（`run_agent.py`、`cli.py`、`gateway/`、`agent/`、
> 顶层 `tools/`、`toolsets.py`、`model_tools.py`、`matlens_cli/`）**不许改动**。
> 所有定制只落在本目录（`matlens_kit/`）、`tests/kit/`、根目录启动脚本。

## 启动

```powershell
cd D:\MatLens
.\.venv\Scripts\python.exe -m matlens_kit.api.server --port 7896
```

或直接双击 `start-matlens.bat`（cmd）/ 运行 `.\start.ps1`（PowerShell，
启动前自动检查 7896 端口是否被占）。启动后访问 <http://127.0.0.1:7896>，
健康检查：<http://127.0.0.1:7896/api/health>。

## 架构

```
浏览器 / 前端
   │  HTTP (JSON) + SSE (事件流对话)
   ▼
FastAPI app  (matlens_kit/api/server.py)
   │  _no_store_static 中间件（调试期静态资源不缓存）
   │  全局异常 handler（未捕获异常统一返回 {"ok":false,"error":...} 500）
   │
   ├── include_router ──► api/sessions_api.py     /api/sessions   会话管理
   ├── include_router ──► api/kb_api.py           /api/kb        本地知识库
   ├── include_router ──► api/mem_api.py           /api/mem       持久记忆
   ├── include_router ──► api/graph_api.py         /api/graph     知识图谱抽取
   ├── include_router ──► api/config_api.py        /api/config    配置读写
   ├── include_router ──► api/approval.py          /api/approval  工具审批
   ├── include_router ──► api/papers_api.py        /api/papers    论文工坊
   ├── include_router ──► api/experiment_api.py   /api/experiment 实验记录
   └── include_router ──► api/tools_api.py        /api/tools     材料工具列表
   │
   ├──► paper/   论文工坊：7 步状态机(engine) + SQLite(db) + 导出(export)
   │             + 质量巡检(quality) + 提示词(prompts) + 文献检索(search)
   ├──► rag/     本地知识库（向量召回，plugins/local_rag 为其 RAG 实现）
   ├──► tools/   材料计算工具（摩尔质量/溶液配制/带隙/单位换算/配平/拟合…）
   │             通过 Hermes registry 注册到 toolset="matlens_material"
   └──► ui/common.py   agent 实例池 + run_conversation（SSE 桥接核心对话）
```

## 目录约定

| 路径 | 职责 |
|------|------|
| `api/` | **HTTP 层**。FastAPI 入口 `server.py` + 9 个 router。只做参数校验、SSE 编排，业务下沉到下面的模块。 |
| `paper/` | **论文工坊**。`engine.py` 是 7 步状态机（topic→search→outline→write→quality→review→export）；`db.py` 是 SQLite 持久层（每个函数都接受可选 `db_path`，测试传临时库）；`export.py` 导出 md/tex；`quality.py` 质量巡检；`prompts.py` 提示词模板。 |
| `rag/` | **本地知识库**。`kb.py` 为知识库接口；`plugins/local_rag/` 是其具体 RAG 后端。 |
| `tools/` | **材料工具**。全部离线计算，通过 Hermes `tools.registry` 注册（toolset=`matlens_material`）。 |
| `ui/common.py` | **agent 池与对话桥**。`get_agent()`/`get_agent_timed()` 按 session 缓存 AIAgent 实例；`run_conversation()` 把核心对话循环接到 SSE 回调。 |
| `ui/tui/`、`ui/web/` | 终端 UI（Ink）与 Gradio 页面（次要界面）。 |

真实用户数据在 `~/.matlens/`（`papers.db`、`state.db`、`graph.json`）。
**测试绝不读写这些文件**——一律用临时目录 / 临时 `db_path`。

## 如何新增一个 router

1. 在 `api/` 下新建 `xxx_api.py`，参照 `papers_api.py` 顶部：

   ```python
   from fastapi import APIRouter
   _router = APIRouter(prefix="/api/xxx", tags=["xxx"])

   @_router.get("/")
   def list_xxx():
       return {"ok": True, "data": []}
   ```

2. 在**唯一允许修改的后端文件** `api/server.py` 里挂载（与现有 9 个 router 同样的两行）：

   ```python
   from matlens_kit.api.xxx_api import _router as _xxx_router  # noqa: E402
   app.include_router(_xxx_router)
   ```

   `server.py` 是本目录中唯一可碰的后端文件；其余业务逻辑新建独立模块，
   由 router 调用，不要往 `server.py` 里堆业务代码。

## 如何新增一个材料工具

参照 `tools/computation.py` 末尾的注册段。工具是**纯函数**，返回值用
`tool_result()` 包装，再 `registry.register(...)` 挂到 `matlens_material` 工具集：

```python
from tools.registry import registry, tool_result

def my_tool(x: str) -> dict:
    ...  # 离线计算，不调网络/LLM
    return {"x": x, "result": ...}

_MY_SCHEMA = {
    "name": "my_tool",
    "description": "一句话说明它算什么（给模型看）。",
    "parameters": {
        "type": "object",
        "properties": {"x": {"type": "string", "description": "输入"}},
        "required": ["x"],
    },
}

registry.register(
    name="my_tool",
    toolset="matlens_material",
    schema=_MY_SCHEMA,
    handler=lambda args, **kw: tool_result(my_tool(x=args.get("x", ""))),
    description="材料侧一句话描述（列表展示用）。",
    emoji="🧮",
)
```

要点：
- **离线优先**：材料工具默认不依赖网络/LLM；若确实需要额外依赖，用 `check_fn`
  做可用性门控（不可用时该工具自动从 schema 消失，不阻塞其它工具）。
- `handler` 必须返回 JSON 字符串（`tool_result` 已处理）。
- 新工具自动被 Hermes 工具发现机制加载，无需改顶层 `toolsets.py`。
