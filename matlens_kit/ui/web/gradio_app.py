"""Gradio 本地 Web 界面（matlens web）。

- 5 页：智能对话 / 知识库管理 / 工具中心 / 实验工作流 / 系统设置
- 深色科研主题（主色 #165DFF）
- 同进程调用核心（AIAgent / 知识库 / 工具），不重复实现业务逻辑
- 数据统一 ~/.matlens/，与终端完全互通
"""

from __future__ import annotations

import os
import queue
import threading
import traceback
from typing import Any, Dict, List, Optional

import gradio as gr

from matlens_kit.ui import common
from matlens_kit.tools.material_kit import MATERIAL_TOOLS

PRIMARY = "#165DFF"
CSS = """
:root { --primary: #165DFF; }
.gr-button-primary { background: var(--primary) !important; }
.dark { background: #0B1220 !important; }
#app-header { background: linear-gradient(90deg, #0f1c33, #12274d); border-bottom: 1px solid #2A3A5C; }
#app-header h1 { color: #00D4FF; font-weight: 800; }
.gradio-container { background: #0B1220 !important; }
footer { display: none !important; }
"""


# ─────────────────────────────────────────────────────────────
# 智能对话页
# ─────────────────────────────────────────────────────────────
def _chat_worker(agent, message: str, q: queue.Queue) -> None:
    """后台线程跑核心对话，增量推入队列（实现流式）。"""
    try:
        common.run_conversation(agent, message, stream_callback=q.put)
        q.put(None)
    except Exception as exc:  # noqa: BLE001
        q.put(exc)


def chat_fn(message: str, history: List[Dict[str, Any]], kb_name: str):
    """流式对话（用户消息 + 自动知识库检索注入）。"""
    if not message.strip():
        yield history, ""
        return
    history = list(history or [])
    history.append({"role": "user", "content": message})
    yield history, ""
    try:
        agent = common.get_agent(quiet_mode=True)
    except Exception as exc:  # noqa: BLE001
        history.append({"role": "assistant", "content": f"⚠ Agent 初始化失败：{exc}"})
        yield history, ""
        return

    # 知识库自动检索注入（可配置开关：知识库非空时自动增强）
    kb_context = ""
    if kb_name:
        try:
            mgr = common.get_kb_manager()
            kbase = mgr.get(kb_name)
            hits = kbase.query(message, top_k=3)
            if hits:
                kb_context = "\n\n[知识库参考]\n" + "\n".join(
                    f"〔{h['source']}〕{h['text'][:300]}" for h in hits
                )
        except Exception:
            kb_context = ""

    q: queue.Queue = queue.Queue()
    t = threading.Thread(target=_chat_worker, args=(agent, message + kb_context, q), daemon=True)
    t.start()
    partial = ""
    while True:
        item = q.get()
        if item is None:
            break
        if isinstance(item, Exception):
            partial += f"\n\n⚠ 对话失败：{item}"
            break
        partial += str(item)
        yield history + [{"role": "assistant", "content": partial}], ""
    if not partial:
        partial = "（未生成回复）"
    yield history + [{"role": "assistant", "content": partial}], ""


def _kb_names() -> List[str]:
    try:
        return common.get_kb_manager().list_kbs()
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# 知识库管理页
# ─────────────────────────────────────────────────────────────
def kb_refresh():
    mgr = common.get_kb_manager()
    names = mgr.list_kbs()
    active = mgr.active or ""
    lines = []
    for n in names:
        lines.append(f"{'●' if n == active else '○'} {n}")
    return "\n".join(lines) or "（暂无知识库）", gr.Dropdown(choices=names, value=active)


def kb_create(name: str):
    if not name.strip():
        return "⚠ 请输入知识库名", gr.update()
    r = common.get_kb_manager().create(name.strip())
    return (f"✅ 已创建 {name.strip()}" if "created" in r else f"⚠ {r.get('error', '')}"), gr.update()


def kb_switch(name: str):
    if not name:
        return "⚠ 请选择知识库", gr.update()
    r = common.get_kb_manager().switch(name)
    return f"✅ 已切换：{name}" if "active" in r else f"⚠ {r.get('error', '')}", gr.update()


def kb_upload(files, kb_name: str):
    if not files:
        return "⚠ 请选择文件（PDF/TXT/MD）", gr.update()
    if not kb_name:
        return "⚠ 请先创建/选择知识库", gr.update()
    kbase = common.get_kb_manager().get(kb_name)
    paths = [f.name for f in files]
    r = kbase.add_documents(paths)
    lines = [f"📥 导入完成：成功 {r['ok']}，跳过 {r['skipped']}"]
    for err in r.get("errors", []):
        lines.append(f"  ❌ {err['path']}：{err['error']}")
    return "\n".join(lines), gr.update()


def kb_stats(kb_name: str):
    if not kb_name:
        return "请先选择知识库"
    try:
        s = common.get_kb_manager().get(kb_name).stats()
        return f"📚 {s['name']}\n文献：{s['docs']} 篇\n分块：{s['chunks']}\n目录：{s['dir']}"
    except Exception as exc:
        return f"⚠ {exc}"


# ─────────────────────────────────────────────────────────────
# 工具中心页
# ─────────────────────────────────────────────────────────────
TOOL_DESC = {
    "molar_mass": "⚖️ 摩尔质量计算器 —— 解析化学式，输出摩尔质量/元素占比（支持括号与结晶水）",
    "solution_prep": "🧪 溶液配制计算器 —— 摩尔浓度/质量浓度/质量分数三种模式",
    "tauc_bandgap": "⚡ 半导体带隙计算 —— Tauc plot 法（直接/间接），导入 TXT/CSV 紫外吸收数据",
    "experiment_protocol": "🧫 实验方案生成 —— 水热/溶胶凝胶/高温煅烧/电化学 4 套标准模板",
    "lab_notebook_template": "📒 实验记录模板 —— 合成/表征两类标准化 Markdown 模板",
    "chemical_safety": "⚠️ 危险试剂安全 —— 内置常见危险化学品库（防护+应急）",
    "xrd_preprocess": "📈 XRD 数据预处理 —— 背景扣除/平滑/峰位识别",
    "data_normalize": "📉 批量数据归一化 —— minmax/zscore/面积/最大值四种方式",
    "citation_format": "📚 参考文献格式化 —— GB/T 7714 / IEEE / APA",
    "experiment_writing": "✍️ 实验写作润色 —— 材料论文实验部分专业表述建议",
    "rag_search": "📖 知识库检索 —— 本地文献片段检索（带来源标注）",
    "matlens_kb": "📚 知识库管理 —— create/switch/add/ask/list",
}


def tools_render():
    lines = []
    for t in MATERIAL_TOOLS:
        lines.append(f"**{TOOL_DESC.get(t, t)}**")
    return "\n\n".join(lines)


def tool_run(tool_name: str, params: str):
    """工具中心：按名称+JSON 参数调用工具。"""
    if not tool_name:
        return "请选择工具"
    import json

    from model_tools import handle_function_call

    try:
        args = json.loads(params or "{}") if params.strip() else {}
    except json.JSONDecodeError as exc:
        return f"⚠ 参数不是合法 JSON：{exc}"
    try:
        result = handle_function_call(tool_name, args)
        return result if isinstance(result, str) else str(result)
    except Exception as exc:  # noqa: BLE001
        return f"⚠ 调用失败：{exc}\n{traceback.format_exc(limit=3)}"


# ─────────────────────────────────────────────────────────────
# 实验工作流页
# ─────────────────────────────────────────────────────────────
WORKFLOW_TEMPLATES = ["hydrothermal 水热合成", "solgel 溶胶-凝胶", "calcination 高温煅烧", "electrochem 电化学测试"]


def workflow_generate(goal: str, template: str):
    if not goal.strip():
        return "⚠ 请输入研究目标"
    key = template.split()[0]
    from matlens_kit.tools.experiment import experiment_protocol_tool

    r = experiment_protocol_tool(goal=goal.strip(), template=key)
    if "error" in r:
        return f"⚠ {r['error']}"
    lines = [f"## 🧫 实验方案：{r['goal']}", f"**模板**：{r['template']}", "",
             f"**试剂**：{r['reagents']}", f"**仪器**：{r['equipment']}", ""]
    for i, s in enumerate(r["steps"], 1):
        lines.append(f"{i}. {s}")
    lines += ["", f"⚠ **安全提示**：{r['safety']}", "", f"**备注**：{r['notes']}"]
    return "\n".join(lines)


def workflow_record(scenario: str):
    from matlens_kit.tools.experiment import lab_notebook_template_tool

    key = "synthesis" if "合成" in scenario else "characterization"
    r = lab_notebook_template_tool(scenario=key)
    return r.get("markdown", "⚠ 生成失败")


# ─────────────────────────────────────────────────────────────
# 系统设置页
# ─────────────────────────────────────────────────────────────
def settings_load():
    cfg = common.get_config()
    model = cfg.get("model", "")
    provider = (cfg.get("model") and "") or "auto"
    toolsets = cfg.get("toolsets", [])
    return model, provider, ", ".join(toolsets), "深色科研主题", "127.0.0.1", "7860"


def settings_save(model: str, provider: str, kb_auto: bool):
    # 保存到 ~/.matlens/config.yaml（用户配置）
    import yaml
    from matlens_cli.config import load_config

    cfg = load_config()
    if model:
        cfg["model"] = model
    cfg["tools"] = cfg.get("tools", {})
    cfg["tools"]["kb_auto_retrieve"] = kb_auto
    path = os.path.join(os.environ["MATLENS_HOME"], "config.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return f"✅ 设置已保存（{path}）"


# ─────────────────────────────────────────────────────────────
# 应用组装
# ─────────────────────────────────────────────────────────────
def build_app() -> gr.Blocks:
    theme = gr.themes.Base(
        primary_hue=gr.themes.colors.blue,
        secondary_hue=gr.themes.colors.cyan,
        neutral_hue=gr.themes.colors.slate,
        font=[gr.themes.GoogleFont("Noto Sans SC"), "sans-serif"],
    ).set(
        body_background_fill="#0B1220",
        block_background_fill="#111A2E",
        block_border_color="#2A3A5C",
        body_text_color="#D6E4FF",
        block_title_text_color="#00D4FF",
        border_color_primary="#2A3A5C",
        button_primary_background_fill="#165DFF",
        button_primary_text_color="#FFFFFF",
        input_background_fill="#0B1220",
    )

    with gr.Blocks(theme=theme, css=CSS, title="MatLens 材料之镜") as app:
        gr.HTML(
            "<div id='app-header' style='padding:10px 24px;'><h1 style='margin:0;'>"
            "🔬 MatLens 材料之镜 · 本地科研 Agent</h1></div>"
        )
        with gr.Tabs():
            # ── 智能对话 ──
            with gr.Tab("💬 智能对话"):
                with gr.Row():
                    with gr.Column(scale=3):
                        chatbot = gr.Chatbot(type="messages", height=520, label="对话")
                        with gr.Row():
                            msg = gr.Textbox(placeholder="输入消息…（如：计算 TiO2 的摩尔质量）",
                                             lines=2, scale=4, container=False)
                            send = gr.Button("发送", variant="primary", scale=1)
                    with gr.Column(scale=1):
                        kb_sel = gr.Dropdown(_kb_names(), label="知识库（可选，自动检索）", value=None)
                        gr.Markdown("### ⚡ 快捷工具\n"
                                    "· `/calc Fe2O3` 摩尔质量\n· `/exp new` 实验方案\n"
                                    "· `/ref format` 文献格式\n· `/kb` 知识库")
                send.click(chat_fn, [msg, chatbot, kb_sel], [chatbot, msg])
                msg.submit(chat_fn, [msg, chatbot, kb_sel], [chatbot, msg])

            # ── 知识库管理 ──
            with gr.Tab("📚 知识库管理"):
                with gr.Row():
                    with gr.Column(scale=1):
                        kb_list = gr.Textbox(label="知识库列表", interactive=False, lines=8)
                        with gr.Row():
                            new_kb = gr.Textbox(placeholder="新知识库名", container=False, scale=3)
                            create_btn = gr.Button("新建", scale=1)
                        kb_drop = gr.Dropdown(_kb_names(), label="选择知识库")
                        switch_btn = gr.Button("切换激活", variant="primary")
                        kb_status = gr.Textbox(label="知识库统计", interactive=False, lines=5)
                    with gr.Column(scale=1):
                        up = gr.File(label="上传文献（PDF/TXT/MD，可多选）", file_count="multiple",
                                     file_types=[".pdf", ".txt", ".md", ".markdown"])
                        up_btn = gr.Button("导入知识库", variant="primary")
                        upload_result = gr.Textbox(label="导入结果", interactive=False, lines=8)
                create_btn.click(kb_create, [new_kb], [kb_status, kb_drop])
                switch_btn.click(kb_switch, [kb_drop], [kb_status, kb_drop])
                up_btn.click(kb_upload, [up, kb_drop], [upload_result, kb_status])
                kb_drop.change(kb_stats, [kb_drop], [kb_status])
                create_btn.click(kb_refresh, [], [kb_list, kb_drop])
                switch_btn.click(kb_refresh, [], [kb_list, kb_drop])

            # ── 工具中心 ──
            with gr.Tab("🧰 工具中心"):
                with gr.Row():
                    with gr.Column(scale=1):
                        tool_sel = gr.Dropdown(MATERIAL_TOOLS, label="选择工具")
                        tool_params = gr.Textbox(
                            label="参数（JSON）",
                            placeholder='{"formula": "Fe2O3"}  （摩尔质量示例）',
                            lines=3,
                        )
                        tool_run_btn = gr.Button("调用工具", variant="primary")
                    with gr.Column(scale=2):
                        tool_desc = gr.Markdown(tools_render(), label="工具说明")
                        tool_out = gr.Textbox(label="执行结果", interactive=False, lines=12)
                tool_run_btn.click(tool_run, [tool_sel, tool_params], [tool_out])

            # ── 实验工作流 ──
            with gr.Tab("🧫 实验工作流"):
                with gr.Row():
                    with gr.Column(scale=1):
                        exp_goal = gr.Textbox(label="研究目标",
                                              placeholder="如：制备粒径均匀的 TiO2 纳米颗粒")
                        exp_tpl = gr.Dropdown(WORKFLOW_TEMPLATES, label="实验模板", value=WORKFLOW_TEMPLATES[1])
                        exp_btn = gr.Button("生成实验方案", variant="primary")
                        rec_scene = gr.Radio(["材料合成", "表征测试"], label="实验记录模板", value="材料合成")
                        rec_btn = gr.Button("生成记录模板")
                    with gr.Column(scale=2):
                        exp_out = gr.Markdown("实验方案将显示在这里")
                        rec_out = gr.Textbox(label="实验记录模板", interactive=False, lines=10)
                exp_btn.click(workflow_generate, [exp_goal, exp_tpl], [exp_out])
                rec_btn.click(workflow_record, [rec_scene], [rec_out])

            # ── 系统设置 ──
            with gr.Tab("⚙️ 系统设置"):
                with gr.Row():
                    with gr.Column(scale=1):
                        set_model = gr.Textbox(label="默认模型（如 qwen2.5:7b / deepseek-chat）")
                        set_provider = gr.Textbox(label="provider（如 ollama / deepseek / custom）")
                        kb_auto = gr.Checkbox(label="对话时自动检索知识库", value=True)
                        set_host = gr.Textbox(label="监听地址", value="127.0.0.1")
                        set_port = gr.Textbox(label="端口", value="7860")
                        save_btn = gr.Button("保存设置", variant="primary")
                        set_result = gr.Textbox(label="保存结果", interactive=False)
                    with gr.Column(scale=1):
                        gr.Markdown(
                            "### ℹ️ 说明\n"
                            "- 所有数据存于 `~/.matlens/`（配置/记忆/知识库）\n"
                            "- 模型多 provider 任选：Ollama / OpenAI 兼容 / DeepSeek 等\n"
                            "- 终端（`matlens tui`）与 Web 端数据完全互通\n"
                            "- 本机服务，`share=False` 不暴露公网"
                        )
                save_btn.click(settings_save, [set_model, set_provider, kb_auto], [set_result])
    return app


def main(host: str = "127.0.0.1", port: int = 7860, **kwargs: Any) -> None:
    """matlens web 入口。"""
    app = build_app()
    app.queue()
    # _frontend=False：跳过 gradio 的 localhost 探测（离线/受限网络环境）
    # （服务本身照常监听 127.0.0.1，纯本机使用）
    app.launch(server_name=host, server_port=port, share=False, inbrowser=True,
               _frontend=False, quiet=True)


if __name__ == "__main__":
    main()
