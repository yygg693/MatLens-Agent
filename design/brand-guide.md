# MatLens 品牌视觉规范（v1.0）

> 所有文字/UI/Logo 必须适配本规范，不只改名字。

## 🎨 视觉系统

### 主 Logo
- 文件：`assets/brand/matlens-logo-master.jpg`
- 元素：六方晶格（深蓝紫渐变边框 + 集成电路纹路 + ML 字母）+ "matlens" 小写无衬线 + "材料之镜" 中文
- 用途：README 横幅、官网首屏、TUI 启动页、Web 头部、应用图标（缩放后）

### 色彩系统（从 Logo 提取）
| 名称 | 色值 | 用途 |
|---|---|---|
| MatLens Blue | `#165DFF` | 主色（按钮、强调、Logo 起点） |
| MatLens Cyan | `#00D4FF` | 高亮/信息（Logo 左侧高光） |
| MatLens Purple | `#7B5CFF` | 渐变/装饰（Logo 右侧紫） |
| MatLens Dark | `#020617` | 深背景（与 Web 端一致） |
| MatLens Card | `#0F172A` | 面板/卡片 |
| MatLens Border | `#334155` | 边框 |
| MatLens Text | `#F8FAFC` | 主文本 |
| MatLens Dim | `#94A3B8` | 次要文本 |
| Accent Success | `#22C55E` | 成功/确认（保留 Hermes 调色板） |
| Accent Warn | `#F59E0B` | 警告 |
| Accent Error | `#EF4444` | 错误 |

> **渐变方向**：`#165DFF` → `#7B5CFF`（左到右，与 Logo 一致）

### 字体
| 用途 | 字体 | 备选 |
|---|---|---|
| Logo/标题 | 蓝紫渐变小写 "matlens" | — |
| 中文标题 | "材料之镜"（无衬线） | Noto Sans SC / 系统默认 |
| 正文/代码 | 等宽/无衬线 | JetBrains Mono / Inter |

## ✍️ 文字品牌（不只是改名字，要适配视觉）

### 产品签名
- **主名**：`matlens`（小写蓝紫渐变，Logo 字样）
- **中文**：`材料之镜`（Logo 中文）
- **完整签名**：`MatLens 材料之镜`（英文小写 + 中文，蓝紫调）
- **副标题**：`材料科研 AI Agent · 基于 Nous Research 的 Hermes Agent 二次开发`

### 系统提示词（用户每次对话都看到）
- ❌ 旧：`You are Hermes Agent, an intelligent AI assistant created by Nous Research.`
- ✅ 新：`You are MatLens 材料之镜，an intelligent AI assistant for materials science research. MatLens is built on top of Hermes Agent (by Nous Research).`

### README 介绍
- 主标题：`# MatLens 材料之镜`
- Logo 横幅插入开头
- 简介：`MatLens 材料之镜 — 面向材料科研的本地 AI Agent。文献调研 · 性质速查 · 论文工作流 · 领域校验。开源免费，数据本地。基于 Nous Research 的 Hermes Agent 二次开发。`
- Badge 链：License MIT / Version v1.0.0 / Build Status passing / 中文文档

### CLI 启动 banner（TUI/Web 启动）
- 显示 Logo ASCII art（参照 logo 六方晶格 + ML 字符）
- 蓝紫渐变标题 "MatLens 材料之镜"
- 副标：`基于 Nous Research Hermes Agent · 离线纯本地 · 全链路开源`
- 启动语：保留「快速示例 + /help 提示」

### TUI 主题（matlens_kit/ui/tui/theme.py）
- PRIMARY：`#165DFF`（主蓝）
- CYAN：`#00D4FF`（高亮）
- PURPLE：`#7B5CFF`（Logo 紫，渐变点）
- BG/PANEL_BG/BORDER/TEXT/DIM：见色彩系统
- LOGO 渲染：Rich 文本模拟六方晶格（ASCII art + 紫蓝渐变）

### Web 主题（gradio_app.py CSS）
- 主色 `#165DFF` + 紫 `#7B5CFF` 渐变（按钮 hover、链接、强调）
- 背景：`#020617` → `#0F172A` 渐变（呼应 Logo 深色基调）
- Logo 位：每页头部 `MatLens 材料之镜` 文字 + 渐变色

### Help/欢迎/状态文案
- 蓝紫渐变 `[cyan]/[bold cyan]…[/]` 标记
- 关键标题用 `[bold]……[/]`
- 状态符号：`✅ ⚠ 📊 🤖 📚 🧪`

## 🖼️ Logo 资源清单
- `assets/brand/matlens-logo-master.jpg`（源图 144KB）
- 后续生成：favicon-16/32.ico、icon-128.png、banner-wide.png、og-card.png

## 🚫 不允许
- 单独使用 "Hermes Agent" 作为产品名（必须作为致谢的上游）
- 使用不同色系的蓝（必须 `#165DFF` 起）
- 中文写作 "赫尔墨斯" 等音译
- 任何风格不一致的 logo 变体

## ✅ 适配检查清单
- [ ] 系统提示词（对话可见）
- [ ] README/官网文案 + Logo
- [ ] TUI 主题与 ASCII Logo
- [ ] Web 主题与头部
- [ ] Desktop/Web/官网 favicon
- [ ] CLI 启动 banner
- [ ] 所有 `HERMES_*` 环境变量
- [ ] 所有 `Hermes Agent` 文字
