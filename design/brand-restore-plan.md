# MatLens 品牌重制清单（Hermes → MatLens 全量替换）

> 目标：把项目中所有「Hermes 专属」的署名、标志、名称、URL、图标替换为 MatLens，
> 保留上游版权声明（Nous Research）与致谢。扫描于 2026-08-16 全仓。

---

## 一、系统提示词（⚠️ 最关键——用户每次对话可见）

| 文件 | 位置 | 现状 | 处理 |
|---|---|---|---|
| `agent/prompt_builder.py` | L151 | `You are Hermes Agent, an intelligent AI assistant created by Nous Research` | → `You are MatLens 材料之镜，...`（保留 Nous Research 致谢句） |
| 同文件 | L161 | `You run on Hermes Agent (by Nous Research)` | → `You run on MatLens (based on Hermes Agent by Nous Research)` |
| 同文件 | L164 | `https://hermes-agent.nousresearch.com/docs` | → MatLens 文档占位 |

> 注：恢复时因保护「Nous Research」行被跳过，Hermes Agent 字样仍在系统提示词里。

## 二、Logo / 图标（图片资源，需生成 MatLens 标志）

| 资源 | 位置 | 用途 |
|---|---|---|
| `assets/banner.png` | 项目根 | README/官网横幅（含 HERMES 字样） |
| `apps/desktop/assets/icon.png` / `icon.ico` | 桌面应用 | 应用图标 |
| `apps/bootstrap-installer/src-tauri/icons/*` | 安装器 | 128/32px + ico |
| `web/public/favicon.ico` | React Web | 浏览器图标 |
| `website/static/img/logo.png` + favicon 全套 | 官网 | 官网标志 |

> 处理：生成 MatLens 六方晶格风 Logo（深蓝 #165DFF + 青色），替换全部图标位。

## 三、URL 引用（代码内）

| 文件 | 位置 | 现状 | 处理 |
|---|---|---|---|
| `agent/anthropic_adapter.py` | L881/L928 | `https://hermes-agent.nousresearch.com`（HTTP-Referer） | → MatLens 占位（或移除） |
| `agent/auxiliary_client.py` | L1021/L1142 | 同上 | 同上 |
| 各 README / website / web | 多处 | `github.com/NousResearch/hermes-agent`、`hermes-agent.nousresearch.com` | 保留上游链接为致谢，其余 MatLens 化 |

## 四、文件命名（20+ 个 hermes 残留文件名）

| 类型 | 文件 |
|---|---|
| 桌面 TS | `apps/desktop/electron/windows-hermes-path.ts`（+test）、`use-hermes-config.ts`（+test） |
| 测试 | `tests/test_hermes_bootstrap.py`、`test_hermes_constants.py`、`test_hermes_logging.py`、`test_hermes_home_profile_warning.py`、`test_hermes_tools_mcp_server.py` |
| 技能脚本 | `skills/productivity/google-workspace/scripts/_hermes_home.py`、`skills/research/grounded-citations/scripts/_hermes_home.py` |
| 技能目录 | `skills/software-development/inspecting-hermes-desktop-dom` |
| 迁移脚本 | `optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py` |
| 部署 | `setup-hermes.sh`、`docker/s6-rc.d/main-hermes`（+contents.d） |
| 邮箱 | `contributors/emails/*@hermes.*`（上游贡献者邮箱，保留即可） |

## 五、环境变量（HERMES_ 前缀）

| 位置 | 变量 |
|---|---|
| `matlens_cli/auth.py` | `HERMES_PORTAL_BASE_URL` |
| `matlens_cli/diagnostics_upload.py` | `HERMES_DIAGNOSTICS_BASE_URL` |
| `plugins/dashboard_auth/nous/__init__.py` | `HERMES_DASHBOARD_OAUTH_CLIENT_ID` / `HERMES_DASHBOARD_PORTAL_URL` |

> 处理：`HERMES_` → `MATLENS_`（Nous 云端服务 MatLens 不启用，改名保持品牌统一）。

## 六、README / 文档 / 官网

| 位置 | 现状 |
|---|---|
| `apps/desktop/README.md` | `# Hermes Desktop ☤` + 上游徽章/链接 |
| `website/`（52 文件） | 官网全套：Hermes Agent 文案、截图、下载 |
| `web/`（17 文件） | React Web：标题/描述/Hermes 字样 |
| 根 `README.md` | 需重写为 MatLens 完整介绍（含上游致谢） |

## 七、其他

| 项 | 处理 |
|---|---|
| `ui-tui`（TS TUI 界面内 Hermes 字样） | 品牌替换 |
| `contributors/emails/*@hermes.*` | 保留（上游贡献者数据） |
| LICENSE 双版权 | ✅ 已处理（Nous Research 2025 + MatLens 2026） |

---

## 执行建议顺序
1. **系统提示词**（对话可见，先做）
2. **文件名**（test_hermes_* 等 20+ 改名 + import 引用）
3. **环境变量** HERMES_ → MATLENS_
4. **URL** 代码内 Referer/文档链接
5. **README/官网/web/desktop 文案**
6. **Logo/图标**（生成 MatLens 六方晶格标志，替换全部图标位）
