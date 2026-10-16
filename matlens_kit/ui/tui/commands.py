"""MatLens TUI 斜杠命令体系（/kb /tool /exp /calc /ref /model /clear /save /help）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def run_command(line: str) -> Tuple[str, bool]:
    """执行斜杠命令。

    Args:
        line: 用户输入的命令行（以 / 开头）。

    Returns:
        (输出文本, 是否已处理)。未处理返回 ("", False)。
    """
    parts = line.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("/help", "/h", "/?"):
        return _help_text(), True
    if cmd == "/kb":
        return _kb_command(args), True
    if cmd == "/tool":
        return _tool_command(args), True
    if cmd in ("/exp",):
        return _exp_command(args), True
    if cmd in ("/calc",):
        return _calc_command(args), True
    if cmd in ("/ref",):
        return _ref_command(args), True
    if cmd == "/model":
        return _model_command(args), True
    if cmd == "/clear":
        return "", True  # 由调用方处理清屏标记
    if cmd == "/save":
        return _save_command(args), True
    if cmd == "/status":
        return _status_command(), True
    if cmd == "/setup":
        return setup_wizard(), True
    return "", False


def _help_text() -> str:
    return (
        "[cyan]MatLens 终端操作指南[/]\n"
        "\n"
        "[bold]知识库[/]\n"
        "  /kb list              列出知识库\n"
        "  /kb use <name>        切换到知识库\n"
        "  /kb create <name>     创建知识库\n"
        "  /kb add <file...>     导入文献（PDF/TXT/MD）\n"
        "  /kb rebuild           重建当前库索引\n"
        "  /kb off               关闭知识库\n"
        "\n"
        "[bold]工具快捷[/]\n"
        "  /calc <化学式>         计算摩尔质量（如 /calc Fe2O3）\n"
        "  /exp new <目标>        生成实验方案（水热/溶胶凝胶/煅烧/电化学）\n"
        "  /ref format <信息>     格式化参考文献（GB7714/IEEE/APA）\n"
        "  /tool                 查看全部材料工具\n"
        "\n"
        "[bold]系统[/]\n"
        "  /setup                首次配置向导（模型服务商）\n"
        "  /model                切换模型（Hermes 原生选择器）\n"
        "  /clear                清空对话\n"
        "  /save                 保存会话\n"
        "  /status               查看状态\n"
        "  /help                 本帮助\n"
        "  /quit 或 Ctrl+D       退出\n"
    )


def _kb_command(args: List[str]) -> str:
    from matlens_kit.plugins.local_rag import handle_kb_command

    result = handle_kb_command(args) if args else handle_kb_command(["list"])
    return _format_kb_result(result)


def _format_kb_result(result: Dict[str, Any]) -> str:
    """知识库结果 → TUI 文本。"""
    if "error" in result:
        return f"[red]⚠ {result['error']}[/]"
    if "knowledge_bases" in result:
        lines = ["[bold]📚 知识库列表[/]"]
        for k in result["knowledge_bases"]:
            mark = "●" if k == result.get("active") else "○"
            lines.append(f"  {mark} {k}")
        if not result["knowledge_bases"]:
            lines.append("  （暂无，用 /kb create <name> 创建）")
        return "\n".join(lines)
    if "created" in result:
        return f"[green]✅ 已创建知识库：{result['created']}（用 /kb use {result['created']} 激活）[/]"
    if "active" in result:
        return f"[green]✅ 当前知识库：{result['active']}[/]"
    if "deleted" in result:
        return f"[green]🗑 已删除：{result['deleted']}[/]"
    if "ok" in result:
        lines = [f"[bold]📥 导入：成功 {result['ok']}，跳过 {result['skipped']}[/]"]
        for item in result.get("items", []):
            if item.get("skipped"):
                lines.append(f"  ⏭ {item.get('source')}（已存在）")
            else:
                lines.append(f"  ✅ {item.get('source')}：{item.get('chunks')} 分块")
        for err in result.get("errors", []):
            lines.append(f"  ❌ {err['path']}：{err['error']}")
        return "\n".join(lines)
    if "hits" in result:
        lines = [f"[bold]📖 检索命中 {result.get('count', 0)} 条[/]"]
        for i, h in enumerate(result["hits"], 1):
            lines.append(f"  [{i}] [cyan]{h['source']}[/]（相关度 {h.get('score', '-')}）")
            lines.append(f"      {h['text'][:100]}{'…' if len(h['text']) > 100 else ''}")
        return "\n".join(lines)
    if "name" in result and "chunks" in result:
        return f"[bold]📚 {result['name']}[/]：{result['docs']} 文献 / {result['chunks']} 分块\n  目录：{result['dir']}"
    return str(result)


def _tool_command(args: List[str]) -> str:
    from matlens_kit.tools.material_kit import MATERIAL_TOOLS

    lines = ["[bold]🧪 MatLens 材料工具箱[/]", ""]
    desc = {
        "molar_mass": "摩尔质量计算",
        "solution_prep": "溶液配制计算",
        "tauc_bandgap": "Tauc 带隙计算",
        "energy_convert": "能量单位换算",
        "battery_capacity": "电池理论比容量",
        "thermo_gibbs": "热力学判据",
        "lever_rule": "相图杠杆定律",
        "experiment_protocol": "实验方案生成",
        "lab_notebook_template": "实验记录模板",
        "chemical_safety": "危险试剂安全",
        "xrd_preprocess": "XRD 数据预处理",
        "xrd_dspacing": "XRD 晶面间距换算",
        "data_normalize": "数据归一化",
        "experiment_plot": "实验数据可视化",
        "citation_format": "参考文献格式化",
        "experiment_writing": "实验写作润色",
        "rag_search": "知识库检索",
        "matlens_kb": "知识库管理",
    }
    if args:
        name = args[0].lower()
        if name in desc:
            lines.append(f"  [cyan]{name}[/] — {desc[name]}")
            lines.append(f"    对话中说「用 {name} 工具…」即可调用")
            return "\n".join(lines)
        return f"[red]未知工具：{name}[/]（/tool 查看全部）"
    for t in MATERIAL_TOOLS:
        lines.append(f"  · [cyan]{t}[/] — {desc.get(t, '')}")
    lines.append("")
    lines.append("[dim]用法：对话中直接让 Agent 调用，或 /calc /exp /ref 快捷命令[/]")
    return "\n".join(lines)


def _calc_command(args: List[str]) -> str:
    if not args:
        return "[red]用法：/calc <化学式>（如 /calc Fe2O3、/calc Ca(OH)2）[/]"
    formula = args[0]
    from matlens_kit.tools.computation import molar_mass_tool

    r = molar_mass_tool(formula=formula)
    if "error" in r:
        return f"[red]{r['error']}[/]"
    parts = []
    for e in r["elements"]:
        parts.append(f"{e['symbol']} {e['count']}×{e['mass']}（{e['weight_percent']}%）")
    return (
        f"[bold]⚖️ {formula} 摩尔质量：{r['molar_mass_g_mol']} g/mol[/]\n"
        f"  " + " | ".join(parts) + f"\n  [dim]{r['formula_breakdown']}[/]"
    )


def _exp_command(args: List[str]) -> str:
    if len(args) < 2:
        return "[red]用法：/exp new <目标> [模板]（模板：hydrothermal/solgel/calcination/electrochem）[/]"
    goal = " ".join(args[1:]) if args[0] == "new" else " ".join(args)
    template = args[-1] if args[-1] in ("hydrothermal", "solgel", "calcination", "electrochem") else "solgel"
    from matlens_kit.tools.experiment import experiment_protocol_tool

    r = experiment_protocol_tool(goal=goal, template=template)
    if "error" in r:
        return f"[red]{r['error']}[/]"
    lines = [f"[bold]🧫 实验方案：{r['goal']}[/]", f"[cyan]模板：{r['template']}[/]", "",
             f"[bold]试剂[/] {r['reagents']}", f"[bold]仪器[/] {r['equipment']}", ""]
    for i, s in enumerate(r["steps"], 1):
        lines.append(f"  {i}. {s}")
    lines.append("")
    lines.append(f"[yellow]⚠ 安全：{r['safety']}[/]")
    return "\n".join(lines)


def _ref_command(args: List[str]) -> str:
    if not args:
        return "[red]用法：/ref format <风格> <题名> <作者> <期刊>（风格：gb7714/ieee/apa）[/]"
    style = args[1] if len(args) > 1 and args[0] == "format" else "gb7714"
    rest = args[2:] if len(args) > 2 else []
    title = rest[0] if rest else "示例题名"
    authors = rest[1] if len(rest) > 1 else "作者"
    journal = rest[2] if len(rest) > 2 else "期刊名"
    from matlens_kit.tools.writing import citation_format_tool

    r = citation_format_tool(style=style, title=title, authors=authors, journal=journal, year="2026")
    if "error" in r:
        return f"[red]{r['error']}[/]"
    return f"[bold]📚 {style} 格式[/]\n  {r['citation']}"


def _model_command(args: List[str]) -> str:
    """查看/切换模型：/model 查看，/model set <provider> 切换。"""
    import os

    from matlens_kit.ui.common import _resolve_model_config

    if args and args[0] in ("set", "use") and len(args) >= 2:
        provider = args[1].lower()
        return _set_provider(provider, args[2] if len(args) > 2 else "")
    # 显示当前配置
    model, provider = _resolve_model_config("", "")
    lines = ["[bold cyan]🤖 模型配置[/]", ""]
    lines.append(f"  当前模型：{model or '（未设置）'}")
    lines.append(f"  当前 provider：{provider or 'auto'}")
    lines.append("")
    lines.append("[bold]可用 provider（/model set <名称> 切换）：[/]")
    lines.append("  · deepseek — DeepSeek（V3/R1，需 DEEPSEEK_API_KEY）")
    lines.append("  · ollama — 本地模型（需本机 Ollama，模型 qwen2.5:7b 等）")
    lines.append("  · custom — OpenAI 兼容自定义端点（OPENAI_BASE_URL + OPENAI_API_KEY）")
    lines.append("  · auto — 自动检测（默认）")
    lines.append("")
    lines.append("[dim]例：/model set deepseek · /model set ollama qwen2.5:7b · /model set custom[/]")
    return "\n".join(lines)


def _set_provider(provider: str, model: str) -> str:
    """切换 provider 并写入 ~/.matlens/.env（TUI 内即时生效）。"""
    import os

    env_path = os.path.join(os.environ.get("MATLENS_HOME", os.path.expanduser("~/.matlens")), ".env")
    env_lines = []
    if os.path.exists(env_path):
        try:
            env_lines = open(env_path, encoding="utf-8").read().splitlines()
        except Exception:
            env_lines = []
    if provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            return "[red]未找到 DEEPSEEK_API_KEY：请先 /setup 选择 DeepSeek 填入 Key[/]"
        os.environ["MATLENS_PROVIDER"] = "deepseek"
        os.environ["MATLENS_MODEL"] = model or "deepseek-chat"
        return f"[green]✅ 已切换：DeepSeek（{model or 'deepseek-chat'}）[/]"
    if provider == "ollama":
        os.environ["MATLENS_PROVIDER"] = "ollama"
        os.environ["MATLENS_MODEL"] = model or "qwen2.5:7b"
        os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434/v1"
        return f"[green]✅ 已切换：Ollama 本地（{model or 'qwen2.5:7b'}）[/]\n[dim]  base_url: http://127.0.0.1:11434/v1（请确认本机 Ollama 已启动）[/]"
    if provider == "custom":
        base = os.environ.get("OPENAI_BASE_URL")
        key = os.environ.get("OPENAI_API_KEY")
        if not base:
            return "[red]未配置 OPENAI_BASE_URL：请先 /setup 选择 OpenAI 兼容端点[/]"
        os.environ["MATLENS_PROVIDER"] = "custom"
        os.environ["MATLENS_MODEL"] = model or os.environ.get("MATLENS_MODEL", "")
        return f"[green]✅ 已切换：自定义端点（{base}）[/]"
    if provider == "auto":
        os.environ.pop("MATLENS_PROVIDER", None)
        return "[green]✅ 已恢复自动检测[/]"
    return f"[red]未知 provider：{provider}[/]（可用 deepseek / ollama / custom / auto）"


def _save_command(args: List[str]) -> str:
    return "[dim]会话自动持久化（~/.matlens/state.db），/save 为语义化保存提示；退出后可用 matlens --resume 恢复[/]"


def _status_command() -> str:
    from matlens_kit.ui.common import get_kb_manager

    mgr = get_kb_manager()
    kbs = mgr.list_kbs()
    active = mgr.active
    lines = ["[bold]📊 MatLens 状态[/]"]
    lines.append(f"  · 知识库：{'● ' + active if active else '未激活'}（共 {len(kbs)} 个）")
    lines.append(f"  · 模型配置：{'已配置' if _is_model_configured() else '未配置（/setup 引导）'}")
    return "\n".join(lines)


def _is_model_configured() -> bool:
    """检测模型是否已配置（.env 有 key 或 config 有 model）。"""
    import os

    if os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return True
    try:
        from matlens_kit.ui.common import get_config

        cfg = get_config()
        m = cfg.get("model") or {}
        if isinstance(m, dict) and m.get("default"):
            return True
    except Exception:
        pass
    return False


def setup_wizard() -> str:
    """首次使用配置向导（交互式）：选择 provider → 配置 key/端点 → 写入 ~/.matlens/.env。"""
    import os

    env_path = os.path.join(os.environ.get("MATLENS_HOME", os.path.expanduser("~/.matlens")), ".env")
    lines = ["[bold cyan]🧭 MatLens 首次配置向导[/]", ""]
    lines.append("请选择模型服务商：")
    lines.append("  [1] DeepSeek（推荐，国内直连）")
    lines.append("  [2] Ollama（本地模型，离线）")
    lines.append("  [3] OpenAI 兼容（自定义端点）")
    lines.append("  [0] 跳过（稍后用 /setup 再配）")
    print("\n".join(lines))
    try:
        choice = input("请输入数字 [1/2/3/0]：").strip()
    except EOFError:
        return "\n已取消配置"
    env_lines = []
    if os.path.exists(env_path):
        try:
            env_lines = open(env_path, encoding="utf-8").read().splitlines()
        except Exception:
            env_lines = []
    if choice == "1":
        try:
            key = input("请输入 DeepSeek API Key（platform.deepseek.com 获取）：").strip()
        except EOFError:
            return "\n已取消配置"
        if not key:
            return "\n未输入 Key，配置未保存（可用 /setup 重试）"
        env_lines = [l for l in env_lines if not l.startswith("DEEPSEEK_API_KEY")]
        env_lines.append(f"DEEPSEEK_API_KEY={key}")
        os.environ["DEEPSEEK_API_KEY"] = key
        _write_env(env_path, env_lines)
        return "\n[green]✅ DeepSeek 已配置！直接对话即可使用。[/]"
    if choice == "2":
        try:
            model = input("请输入 Ollama 模型名（如 qwen2.5:7b，回车默认 qwen2.5:7b）：").strip() or "qwen2.5:7b"
        except EOFError:
            return "\n已取消配置"
        os.environ["MATLENS_OLLAMA_MODEL"] = model
        lines2 = ["[green]✅ Ollama 配置提示：[/]",
                  f"  模型：{model}",
                  "  使用前请确认本机已安装并运行 Ollama（ollama.com 下载）",
                  "  在 .env 中配置：",
                  "    MATLENS_OLLAMA_MODEL=" + model,
                  "  （对话时若未识别 Ollama，可运行 matlens model 选择 custom + base_url=http://127.0.0.1:11434/v1）"]
        return "\n".join(lines2)
    if choice == "3":
        try:
            base = input("请输入 API 端点 base_url（如 https://api.deepseek.com/v1）：").strip()
            key = input("请输入 API Key（无则回车）：").strip()
            model = input("请输入模型名（如 deepseek-chat）：").strip()
        except EOFError:
            return "\n已取消配置"
        if base:
            env_lines = [l for l in env_lines if not l.startswith("OPENAI_BASE_URL")]
            env_lines.append(f"OPENAI_BASE_URL={base}")
            os.environ["OPENAI_BASE_URL"] = base
        if key:
            env_lines = [l for l in env_lines if not l.startswith("OPENAI_API_KEY")]
            env_lines.append(f"OPENAI_API_KEY={key}")
            os.environ["OPENAI_API_KEY"] = key
        if model:
            os.environ["MATLENS_MODEL"] = model
        _write_env(env_path, env_lines)
        return "\n[green]✅ OpenAI 兼容端点已配置！[/]"
    return "\n已跳过配置（/setup 可随时重新配置）"


def _write_env(path: str, lines: list) -> None:
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
