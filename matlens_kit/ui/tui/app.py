"""MatLens Rich 终端界面主应用 v2（matlens tui）。

布局：顶部状态栏 / 主对话区 / 右侧功能侧边栏 / 底部输入栏。
v2 优化：气泡左右分区、工具调用卡片状态色、顶栏分组、侧栏分类、
         PageUp/Down 滚动、Tab 补全描述预览、输入历史、/toggle tools。
核心：对话与工具调用全部走 AIAgent（run_conversation），知识库走 matlens_kit。
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich import box

from matlens_kit.ui import common
from matlens_kit.ui.tui import theme

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.history import InMemoryHistory
except ImportError:
    PromptSession = None

console = Console()

LOGO = r"""
███╗   ███╗ █████╗ ████████╗██╗     ███████╗███╗   ██╗███████╗
████╗ ████║██╔══██╗╚══██╔══╝██║     ██╔════╝████╗  ██║██╔════╝
██╔████╔██║███████║   ██║   ██║     █████╗  ██╔██╗ ██║███████╗
██║╚██╔╝██║██╔══██║   ██║   ██║     ██╔════╝██║╚██╗██║╚════██║
██║ ╚═╝ ██║██║  ██║   ██║   ███████╗███████╗██║ ╚████║███████║
╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚══════╝╚═╝  ╚═══╝╚══════╝
"""

QUICK_EXAMPLES = [
    ("计算 TiO2 摩尔质量", "⚖️ 计算 Fe2O3 的摩尔质量"),
    ("生成实验方案", "🧫 生成水热合成 TiO2 的实验方案"),
    ("导入文献库", "📚 /kb create mylib 然后 /kb add 论文.pdf"),
]


class SlashCommandCompleter(Completer):
    """斜杠命令 Tab 补全（含功能描述预览）。"""

    COMMANDS: List[Tuple[str, str]] = [
        ("/kb list", "列出知识库"),
        ("/kb use ", "切换知识库"),
        ("/kb create ", "创建知识库"),
        ("/kb add ", "导入文献"),
        ("/kb rebuild", "重建索引"),
        ("/kb off", "关闭知识库"),
        ("/calc ", "摩尔质量计算"),
        ("/exp new ", "生成实验方案"),
        ("/ref format ", "参考文献格式化"),
        ("/tool", "查看全部工具"),
        ("/toggle tools", "显示/隐藏工具调用"),
        ("/model", "切换模型"),
        ("/clear", "清空对话"),
        ("/save", "保存会话"),
        ("/status", "查看状态"),
        ("/help", "查看帮助"),
        ("/quit", "退出"),
    ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        word = text.split()[-1] if text.split() else ""
        prefix = "/" + word if not word.startswith("/") else word
        for cmd, desc in self.COMMANDS:
            if cmd.startswith(prefix) and cmd != text:
                yield Completion(cmd, start_position=-len(word), display_meta=desc)


def build_key_bindings():
    """Enter 发送，Ctrl+J 换行，↑/↓ 历史（PromptSession 内置），Ctrl+D 退出。"""
    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        event.current_buffer.validate_and_handle()

    @kb.add("c-j")
    def _(event):
        event.current_buffer.insert_text("\n")

    @kb.add("escape", "enter")
    def _(event):
        event.current_buffer.insert_text("\n")

    return kb


# ─────────────────────────────────────────────────────────────
# 工具调用卡片解析
# ─────────────────────────────────────────────────────────────
def _extract_tool_calls(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 run_conversation 返回的 messages 提取工具调用记录。"""
    calls: List[Dict[str, Any]] = []
    try:
        for m in result.get("messages", []):
            if isinstance(m, dict):
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        fn = (tc.get("function") or {}).get("name", "?")
                        args = (tc.get("function") or {}).get("arguments", "")
                        calls.append({"name": fn, "args": str(args)[:200], "status": "done"})
                elif m.get("role") == "tool":
                    calls.append({"name": "tool_result", "result": str(m.get("content", ""))[:200]})
    except Exception:
        pass
    return calls


def _format_tool_card(call: Dict[str, Any]) -> Text:
    """工具调用卡片（状态色边框 + 折叠信息）。"""
    name = call.get("name", "?")
    if name == "tool_result":
        return Text(f"  └ 结果：{call.get('result', '')}", style=theme.DIM)
    args = call.get("args", "")
    if call.get("status") == "running":
        return Text(f"  🔧 {name} …", style=f"bold {theme.TOOL_RUNNING}")
    return Text(f"  🔧 {name}({args[:80]})", style=f"bold {theme.TOOL_OK}")


class MatLensTUI:
    """MatLens 终端主界面 v2。"""

    def __init__(self, model: str = "", provider: str = "") -> None:
        self.model = model
        self.provider = provider
        self.agent = None
        self.console = Console()
        self.messages: List[Dict[str, Any]] = []
        self.tool_calls: List[Dict[str, Any]] = []  # 最近一轮工具调用
        self.kb_active: Optional[str] = None
        self.show_tools = True            # /toggle tools
        self._view_offset = 0             # 对话滚动偏移
        self._input_mode = "对话"          # 输入模式提示
        # 启动即解析模型显示（/model set 后由 _sync_model 刷新）
        try:
            m, p = common._resolve_model_config(model, provider)
            self.model = m or "未配置"
            self.provider = p or "auto"
        except Exception:
            pass

    def _sync_model(self) -> None:
        """刷新模型显示（/model set 后调用）。"""
        try:
            m, p = common._resolve_model_config("", "")
            self.model = m or "未配置"
            self.provider = p or "auto"
        except Exception:
            pass

    # ── 渲染 ──────────────────────────────────────────────
    def _render(self, streaming_text: str = "") -> None:
        self.console.clear()
        self.console.print(self._build_layout(streaming_text), justify="left")

    def _build_layout(self, streaming_text: str = "") -> Group:
        header = self._build_header()
        body = self._build_body(streaming_text)
        sidebar = self._build_sidebar()
        layout = Table.grid(expand=True, padding=(0, 0))
        layout.add_column(ratio=3)
        layout.add_column(ratio=1, min_width=28)
        layout.add_row(header)
        layout.add_row(body, sidebar)
        layout.add_row(self._build_footer())
        return layout

    def _build_header(self) -> Panel:
        from matlens_kit import __version__

        now = time.strftime("%H:%M:%S")
        # 单行紧凑：品牌 | 模型 | 知识库 | 时间
        text = Text()
        text.append("  MatLens 材料之镜 ", style=f"bold {theme.CYAN}")
        text.append(f"v{__version__}", style=theme.DIM)
        text.append("  │  ", style=theme.BORDER)
        text.append(f"模型: {self.model or '未配置'}", style=theme.TEXT)
        text.append("  │  ", style=theme.BORDER)
        text.append(f"知识库: {self.kb_active or '未激活'}", style=theme.TEXT)
        if not self.show_tools:
            text.append("  │  ", style=theme.BORDER)
            text.append("工具隐藏", style=theme.DIM)
        text.append("  ", style=theme.BORDER)
        text.append(now, style=theme.DIM)
        return Panel(text, style=theme.BORDER, box=box.ROUNDED, padding=(0, 1))

    def _build_body(self, streaming_text: str = "") -> Panel:
        if not self.messages and not streaming_text:
            content = self._build_welcome()
            return Panel(content, title="对话", border_style=theme.PRIMARY, padding=(1, 2))
        items: List[Any] = []
        # 消息窗口（滚动偏移）
        start = max(0, len(self.messages) - 30 - self._view_offset)
        for m in self.messages[start:]:
            if m.get("role") == "user":
                items.append(self._user_bubble(m["content"]))
            elif m.get("kind") == "cmd":
                # 命令输出：Rich 标记直接渲染（[cyan] 等）
                items.append(self._cmd_bubble(m["content"]))
            else:
                items.append(self._ai_bubble(m["content"]))
        # 工具调用卡片（最近一轮，toggle 控制）
        if self.show_tools and self.tool_calls:
            items.append(self._tool_panel())
        if streaming_text:
            try:
                items.append(self._ai_bubble(streaming_text, streaming=True))
            except Exception:
                items.append(Text(streaming_text))
        return Panel(Group(*items), title="对话", border_style=theme.PRIMARY,
                     padding=(1, 2))

    def _user_bubble(self, content: str) -> Panel:
        """用户消息：右对齐、青色前缀。"""
        text = Text()
        text.append(" 你 ", style=f"bold {theme.CYAN}")
        text.append("  ")
        text.append(content, style=theme.TEXT)
        return Panel(text, border_style=theme.PRIMARY, box=box.ROUNDED,
                     padding=(0, 1))

    def _cmd_bubble(self, content: str) -> Panel:
        """命令输出：Rich 标记文本渲染（支持 [cyan] 等）。"""
        return Panel(Text.from_markup(content), border_style=theme.BORDER,
                     box=box.ROUNDED, padding=(0, 1))

    def _ai_bubble(self, content: str, streaming: bool = False) -> Panel:
        """AI 消息：左对齐、白色主体。"""
        mark = "… " if streaming else ""
        inner = Text(f"{mark}", style=theme.DIM)
        try:
            md = Markdown(content, style=theme.TEXT)
            return Panel(md, border_style=theme.SUCCESS if streaming else theme.BORDER,
                         box=box.ROUNDED, padding=(0, 1))
        except Exception:
            inner.append(content, style=theme.TEXT)
            return Panel(inner, border_style=theme.BORDER, box=box.ROUNDED, padding=(0, 1))

    def _tool_panel(self) -> Panel:
        lines = [Text("🔧 工具调用", style=f"bold {theme.CYAN}")]
        for c in self.tool_calls:
            lines.append(_format_tool_card(c))
        return Panel(Group(*lines), title="工具", border_style=theme.BORDER,
                     box=box.SQUARE, padding=(0, 1))

    def _build_sidebar(self) -> Panel:
        groups = [
            ("⚖️ 计算", ["/calc 摩尔质量", "/exp 实验方案"]),
            ("🧪 实验", ["/ref 文献格式", "/tool 全部工具"]),
            ("📊 数据", ["/kb 知识库", "/status 状态"]),
            ("⌨️ 快捷键", ["Enter 发送", "Ctrl+J 换行", "Tab 补全", "↑↓ 历史", "PgUp/Dn 滚动"]),
        ]
        lines: List[Any] = []
        for title, items in groups:
            lines.append(Text(f"── {title} ──", style=f"bold {theme.CYAN}"))
            for it in items:
                lines.append(Text(f"  {it}", style=theme.TEXT if it.startswith("/") else theme.DIM))
            lines.append(Text(""))
        return Panel(Group(*lines), title="侧栏", border_style=theme.BORDER, padding=(1, 1))

    def _build_footer(self) -> Panel:
        mode = f"模式：{self._input_mode}"
        hint = " /help 查看命令" if self._input_mode == "对话" else " 输入 / 开头命令"
        return Panel(Text(mode + hint, style=theme.DIM),
                     style=theme.BORDER, box=box.ROUNDED, padding=(0, 1))

    def _build_welcome(self) -> Group:
        items = [
            Markdown("**欢迎使用 MatLens 材料之镜**\n\n直接输入问题与 Agent 对话，或试试：\n"),
        ]
        for label, cmd in QUICK_EXAMPLES:
            items.append(Text(f"  {label}：", style=theme.DIM))
            items.append(Text(f"    {cmd}", style=f"bold {theme.CYAN}"))
        items.append(Text(""))
        items.append(Text("输入 /help 查看全部命令", style=theme.DIM))
        return Group(*items)

    # ── 输入 ──────────────────────────────────────────────
    def _input_session(self):
        if PromptSession is None:
            raise RuntimeError("需要 prompt_toolkit：pip install prompt_toolkit")
        return PromptSession(
            completer=SlashCommandCompleter(),
            key_bindings=build_key_bindings(),
            history=InMemoryHistory(),
            multiline=True,
            prompt_continuation="… ",
        )

    # ── 对话 ──────────────────────────────────────────────
    def _ensure_agent(self):
        if self.agent is None:
            self.agent = common.get_agent(model=self.model, provider=self.provider, quiet_mode=True)
            if not self.model:
                self.model = getattr(self.agent, "model", "") or "unknown"

    def _sync_kb(self) -> None:
        try:
            mgr = common.get_kb_manager()
            self.kb_active = mgr.active
        except Exception:
            self.kb_active = None

    def _run_hermes_model_picker(self) -> None:
        """复用 Hermes 原生模型选择器（matlens model 的完整交互流程）。

        provider 选择 → 凭证提示 → 模型选择 → 配置持久化，全部走原生实现。
        """
        self._input_mode = "模型切换"
        self._render()
        try:
            # 原生选择器用 input()/print() 交互：TUI 主循环暂停，终端切到原生流程
            from matlens_cli.main import select_provider_and_model

            select_provider_and_model(args=None)
            self.console.print("")
            self.console.print("[green]模型配置完成 ✅ 返回终端界面[/]")
        except Exception as exc:  # noqa: BLE001
            self.console.print(f"[red]模型切换失败：{exc}[/]")
        self._sync_model()
        self._input_mode = "对话"
        self._render()

    def _friendly_error(self, exc: Exception) -> str:
        """友好错误（不暴露堆栈）。"""
        msg = str(exc)
        if "No module named" in msg:
            return "缺少依赖：请运行 pip install -r requirements.txt 后重试"
        if "401" in msg or "403" in msg or "API key" in msg or "api key" in msg:
            return "模型 API 配置无效：请检查 ~/.matlens/.env 的 API Key，或运行 matlens model 重新配置"
        if "429" in msg:
            return "模型服务限流：请稍后重试"
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            return "请求超时：请检查网络或模型服务是否可用"
        if "初始化" in msg or "init" in msg.lower():
            return "Agent 初始化失败：请运行 matlens doctor 检查环境"
        return f"操作失败：{msg[:120]}（详情见日志）"

    def send_message(self, text: str) -> None:
        """发送消息并渲染流式回复。"""
        self.messages.append({"role": "user", "content": text})
        self.tool_calls = []
        self._view_offset = 0
        self._render()
        try:
            self._ensure_agent()
        except Exception as exc:
            self.messages.append({"role": "assistant", "content": "⚠ " + self._friendly_error(exc)})
            self._render()
            return

        buffer: List[str] = []

        def on_delta(delta):
            if delta is None:
                return
            buffer.append(str(delta))
            try:
                self._render("".join(buffer))
            except Exception:
                pass

        try:
            result = common.run_conversation(self.agent, text, stream_callback=on_delta)
            reply = result.get("final_response") or "".join(buffer)
            if not reply:
                reply = "（未生成回复）"
            self.messages.append({"role": "assistant", "content": reply})
            # 提取工具调用记录
            calls = _extract_tool_calls(result)
            if calls:
                self.tool_calls = calls
        except Exception as exc:
            self.messages.append({"role": "assistant", "content": "⚠ " + self._friendly_error(exc)})
        self._render()

    # ── 主循环 ────────────────────────────────────────────
    def run(self) -> int:
        self._print_splash()
        self._sync_kb()
        try:
            session = self._input_session()
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/]")
            return 2
        self._render()
        while True:
            try:
                line = session.prompt("❯ ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print(f"\n[{theme.DIM}]再见 👋[/]")
                return 0
            if not line:
                continue
            low = line.lower()
            if low in ("/quit", "/exit", "exit", "quit", "q"):
                console.print(f"[{theme.DIM}]再见 👋[/]")
                return 0
            if low == "/clear":
                self.messages.clear()
                self.tool_calls = []
                self._render()
                continue
            if low in ("/toggle tools", "/toggle"):
                self.show_tools = not self.show_tools
                self._render()
                continue
            if low.startswith("/pgup") or low == "pageup":
                self._view_offset = min(self._view_offset + 10, max(0, len(self.messages) - 10))
                self._render()
                continue
            if low.startswith("/pgdn") or low == "pagedown":
                self._view_offset = max(0, self._view_offset - 10)
                self._render()
                continue
            if low == "/model" or low.startswith("/model "):
                # 复用 Hermes 原生模型选择器（matlens model 完整流程）
                self._run_hermes_model_picker()
                continue
            if line.startswith("/"):
                from matlens_kit.ui.tui.commands import run_command

                self._input_mode = "命令"
                output, handled = run_command(line)
                if handled:
                    if any(k in low for k in ("/kb use", "/kb off", "/kb create", "/kb switch")):
                        self._sync_kb()
                    if "/model set" in low or low == "/model":
                        self._sync_model()
                    # 命令输出标记 kind=cmd：用 Rich 标记文本渲染（[cyan] 等）
                    self.messages.append({"role": "assistant", "kind": "cmd", "content": output})
                    self._render()
                    self._input_mode = "对话"
                    continue
                self._input_mode = "对话"
            self.send_message(line)

    def _print_splash(self) -> None:
        console.print(f"[bold {theme.CYAN}]{LOGO}[/]", justify="center")
        console.print(f"[{theme.DIM}]材料之镜 · 材料科研 AI Agent · 终端界面[/]".center(60))
        console.print("")
        console.print(f"[{theme.DIM}]快速示例：[/]".center(60))
        for _, cmd in QUICK_EXAMPLES:
            console.print(f"[bold {theme.CYAN}]  {cmd}[/]")
        console.print("")
        # 首次使用引导：未配置模型时提示配置向导
        from matlens_kit.ui.tui.commands import _is_model_configured

        if not _is_model_configured():
            console.print(f"[bold {theme.WARN}]⚠ 检测到尚未配置模型：[/]")
            console.print(f"[{theme.WARN}]  输入 /setup 进入首次配置向导（选择 DeepSeek / Ollama / 自定义端点）[/]")
            console.print("")
        console.print(f"[{theme.DIM}]输入 /help 查看命令 · 直接提问开始对话[/]".center(60))
        console.print("")


def main(model: str = "", provider: str = "") -> int:
    """matlens tui 入口。"""
    return MatLensTUI(model=model, provider=provider).run()
