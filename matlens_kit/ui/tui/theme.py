"""MatLens TUI 深色科研主题（设计规范：Modern Dark / 深蓝黑 + 青色 + 成功绿）。"""

from __future__ import annotations

# 主色调（对齐 Web 端 #165DFF 与设计系统 Modern Dark）
PRIMARY = "#165DFF"        # 主蓝（Logo 起点）
CYAN = "#00D4FF"           # 青色高亮（Logo 左侧高光）
PURPLE = "#7B5CFF"         # 紫（Logo 渐变点，文字/装饰用）
BG = "#020617"             # 深蓝黑背景（设计系统 --color-background）
PANEL_BG = "#0F172A"       # 面板背景（--color-primary）
PANEL_BG_2 = "#1A1E2F"     # 二级面板（--color-muted）
BORDER = "#334155"         # 边框（--color-border）
TEXT = "#F8FAFC"           # 主文本（--color-foreground）
DIM = "#94A3B8"            # 次要文本（--color-muted-foreground）
SUCCESS = "#22C55E"        # 成功（--color-accent）
ERROR = "#EF4444"          # 错误（--color-destructive）
WARN = "#F59E0B"           # 警告
USER_BUBBLE = "#123B7A"    # 用户气泡（深蓝）
AI_BUBBLE = "#1A1E2F"      # AI 气泡（深灰）
TOOL_RUNNING = "#F59E0B"   # 工具执行中（黄）
TOOL_OK = "#22C55E"        # 工具成功（绿）
TOOL_FAIL = "#EF4444"      # 工具失败（红）
