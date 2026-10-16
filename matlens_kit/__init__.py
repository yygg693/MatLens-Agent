"""MatLens 材料之镜 · 垂直业务层（matlens_kit）。

材料科研专属能力全部在此包内实现，通过 Hermes 原生注册机制接入：
- matlens_kit.tools.material_kit   材料领域 10 工具（registry.register）
- matlens_kit.plugins.local_rag    本地文献知识库插件
- matlens_kit.rag                  RAG 核心实现（FAISS + 复用主 provider 嵌入）

零侵入 Hermes 核心调度：仅 tools/matlens_kit_bridge.py 负责 import 本包触发注册。
"""

__version__ = "0.1.0"
APP_NAME = "MatLens"
APP_NAME_ZH = "材料之镜"
