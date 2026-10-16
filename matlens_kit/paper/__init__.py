# -*- coding: utf-8 -*-
"""论文工坊 · matlens 深度定制（主推功能）。

- db.py      论文数据层（papers.db SQLite）
- engine.py  工作流引擎（STAGES 状态机 + 断点续写）
- prompts.py 7 份角色 prompt（材料科研场景）
- quality.py 质量巡检（引用核验/结构检查/AI 味启发式）
- export.py  导出（Markdown + LaTeX + GB/T 7714）
"""
__version__ = "0.1.0"
