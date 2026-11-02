# Hermes → MatLens 改名清单（分类过审稿）

> 用途：把全仓 `hermes` 残留按**能否安全改**分成三类，逐条列出、标注风险与建议动作。
> 本文档只做盘点与建议，**未执行任何改名**。
>
> 生成时间：2026-10-29 · 基线提交 `480c6ce` · 仓库 `yygg693/MatLens-Agent`

---

## 0. 一句话结论

| 类别 | 规模 | 能否现在做 | 风险 |
|---|---|---|---|
| **A 类：已经坏了的** | 7 处 | 能，且应该现在就做 | **已在造成真实故障** |
| **B 类：可安全改（纯内部）** | 约 180 处 | 能，机械替换 | 极低 |
| **C 类：需保留（对外契约）** | 约 40 处 | **不能**，需双写或版本化 | 高 |
| **D 类：需迁移（磁盘路径）** | 约 60 处 | **不能**，需数据迁移方案 | 高 |
| **E 类：文档与网站** | 约 2000 处 | 单独排期，与代码解耦 | 低 |

> **最重要的发现**：改名不是「审美问题」——**桌面端与后端已经因为改名分叉，处于各自读不同配置目录的状态**（A2）。
> Python 侧早已完成 `MATLENS_*` 迁移，桌面端是唯一还在用 `HERMES_*` 的那半边。
> 换句话说：**这些不是「待改名的旧代码」，而是「已经坏了的代码」**。

---

## 0.5 A 类速览（按严重度排序）

| # | 问题 | 后果 | 一句话修法 |
|---|---|---|---|
| **A2** | `HERMES_HOME` vs `MATLENS_HOME` | **桌面端与后端用两个不同的配置目录**，用户配置/记忆/技能后端全读不到 | spawn 时显式传 `MATLENS_HOME: HERMES_HOME` |
| **A1+A4** | session header 名 + token 变量名两端对不上 | 敏感端点 **401** | header 改 `X-MatLens-Session-Token` + 传 `MATLENS_DASHBOARD_SESSION_TOKEN` |
| **A3** | `HERMES_PORTAL_BASE_URL` vs `MATLENS_PORTAL_BASE_URL` | 桌面端连不上门户 | 双读（新名优先） |
| **A5** | `HERMES_DESKTOP_TERMINAL` vs `MATLENS_DESKTOP_TERMINAL` | 平台提示不生效（**测试却全绿**） | 直接改 |
| A6 | 上述 7 个变量的完整清单 | — | 见 §1 A6 |
| A7 | 12 个不存在的导出 | `typecheck` 跑不通 | 已修 |
| A8 | 重复 interface 声明 | 字段静默合并 | 已修 |

**A2 单独拎出来说**：后端默认 `~/.matlens`（`matlens_kit/api/__init__.py:14`），桌面端默认 `~/.hermes` / `%LOCALAPPDATA%\hermes`（`main.ts:640`），而桌面端 spawn 后端时**一个 `MATLENS_HOME` 都没传**（grep 零结果）。这不是「不一致」，这是**两个系统在用两套目录**。

---

## 1. A 类：已经坏了的（最高优先级）

这几项不是「改名不彻底」，是**现在就在出错**。

### A1. 桌面端 HTTP header 名与后端不匹配 —— 已导致 token 校验失效

**事实**：

| 端 | 位置 | header 名 |
|---|---|---|
| 后端 | `matlens_cli/web_server.py:514` | `_SESSION_HEADER_NAME = "X-MatLens-Session-Token"` |
| Web 端 | `web/src/lib/api.ts:41` | `X-MatLens-Session-Token` ✓ |
| 桌面端 | `apps/desktop/electron/main.ts:4668` | `X-Hermes-Session-Token` ✗ |
| 桌面端 | `apps/desktop/electron/main.ts:4767` | `X-Hermes-Session-Token` ✗ |

后端 `_has_valid_session_token()`（`web_server.py:577`）**只认两个头**：`X-MatLens-Session-Token` 或 `Authorization: Bearer <token>`。桌面端发的旧名头会被直接忽略。

**影响**：`fetchJson(url, token)` 的调用点全部受影响（16 处），包括 `/api/status`、`/api/ssh/ownership`、`/api/auth/ws-ticket` 等。在 loopback + `--insecure` 模式下（即 `_SESSION_TOKEN` 生效、非 OAuth/bearer 的那条路），需要 token 的敏感端点会返回 **401 Unauthorized**。

**建议动作**：桌面端两处 header 改为 `X-MatLens-Session-Token`。**注意**：旧名要不要保留兼容？后端已完全不支持旧名，说明旧名从未真正生效过（改名时后端先改了），所以**直接改、不需要双写**。

**风险**：低。但改完必须验证 loopback 模式的插件安装/启用路径（那几个是 `_require_token` 保护的端点）。

---

### A2. `HERMES_HOME` vs `MATLENS_HOME` —— 桌面端和后端在用两个不同的配置目录（最严重）

**事实**：

| 端 | 位置 | 读取的变量 | 默认目录 |
|---|---|---|---|
| 桌面端 | `main.ts:640` | `HERMES_HOME` | `~/.hermes` / `%LOCALAPPDATA%\hermes` |
| 后端 | `matlens_kit/api/__init__.py:14` | `MATLENS_HOME` | `~/.matlens` |

```python
# matlens_kit/api/__init__.py:14
os.environ.setdefault("MATLENS_HOME", os.path.expanduser("~/.matlens"))
```

```ts
// main.ts:9570 附近 —— spawn 后端时并没有传 MATLENS_HOME
```

`grep -n "MATLENS_HOME" apps/desktop/electron/main.ts` → **零结果**。桌面端把 `HERMES_HOME`（其值为 `~/.hermes` 一类）放进子进程环境，但**后端根本不读这个变量**，后端于是落到自己的默认 `~/.matlens`。

**影响**：桌面端用户配的 API key、模型、**记忆**、技能、插件 —— 后端一个都读不到。表现是「桌面端启动成功但行为像全新安装」。

**注意**：`MATLENS_HOME` 的默认已经是 `~/.matlens`，说明 Python 侧**已经完成迁移**；桌面端是唯一还在用旧名的那个。

**建议动作**（按优先级）：
1. 桌面端 spawn 后端时**显式传 `MATLENS_HOME: HERMES_HOME`** —— 让两端指向同一目录。这一步最小、最关键。
2. 桌面端读配置时**双读** `MATLENS_HOME || HERMES_HOME`，让用户在 `.env` / 系统环境里设 `MATLENS_HOME` 也能生效。
3. 目录名本身（`~/.hermes` → `~/.matlens`）属于 D 类，另行处理 —— **但这一步做完，桌面端与后端的一致性就已经建立了**。

**风险**：低（只是让两端对齐）。**收益**：可能直接修掉「桌面端读不到用户配置」这一整类问题。

---

### A3. 桌面端读旧的环境变量名，后端已改新名

**事实**：

| 位置 | 读的名字 |
|---|---|
| Python 后端 | `matlens_cli/auth.py:2438` → `MATLENS_PORTAL_BASE_URL` ✓（`NOUS_PORTAL_BASE_URL` 兜底） |
| 桌面端 | `apps/desktop/electron/main.ts:7221` → `HERMES_PORTAL_BASE_URL` ✗ |

```ts
// main.ts:7221
const raw = process.env.HERMES_PORTAL_BASE_URL || process.env.NOUS_PORTAL_BASE_URL || DEFAULT_NOUS_PORTAL_URL
```

**影响**：桌面端连不上门户 —— 用户在桌面端设 `MATLENS_PORTAL_BASE_URL` 指向自建/staging 门户时**不生效**，因为桌面端只认 `HERMES_PORTAL_BASE_URL`。而 `auth.py:2427` 的文档字符串里还写着 `HERMES_PORTAL_BASE_URL=...` 的旧示例，会误导用户继续用旧名。

**建议动作**：桌面端改成 `MATLENS_PORTAL_BASE_URL || HERMES_PORTAL_BASE_URL || NOUS_PORTAL_BASE_URL || 默认`（**双读**，因为环境变量是对外契约，不能直接断）。

**风险**：低。但要注意这是「双读」而非「直接改」—— 与 A1 的 header 不同。

---

### A4. 桌面端 spawn 后端时传的 4 个环境变量，后端已改读新名

**事实** —— 桌面端 `main.ts:9575-9584` 传给子进程：

```ts
HERMES_DASHBOARD_SESSION_TOKEN: token,
HERMES_DESKTOP: '1',
HERMES_WEB_DIST: webDist,
...(readyFile ? { HERMES_DESKTOP_READY_FILE: readyFile } : {})
```

后端 `matlens_cli/` 读的却是：

| 桌面端传 | 后端读 | 位置 | 后果 |
|---|---|---|---|
| `HERMES_DASHBOARD_SESSION_TOKEN` | `MATLENS_DASHBOARD_SESSION_TOKEN` | `web_server.py:510` | 后端**自己随机生成** token，桌面端无从得知 → 桌面端后续所有带 token 的请求全 401 |
| `HERMES_WEB_DIST` | `MATLENS_WEB_DIST` | `web_server.py:137` | 后端回落到默认 `web_dist` 路径，不用桌面端指定的那个 |
| `HERMES_DESKTOP` | `MATLENS_DESKTOP` | 多处 | 后端认不出「这是桌面端 spawn 的」标记，cron tick 循环等行为可能不触发 |
| `HERMES_DESKTOP_READY_FILE` | `MATLENS_DESKTOP_READY_FILE` | — | 就绪文件路径丢失 |

**这是 A1 的根因**：桌面端拿不到后端生成的 token（`_SESSION_TOKEN` 是后端随机生成的，不是桌面端传的），所以发出去的 header 值本来就是错的。**两处必须一起改** —— 只改 header 名不够。

### A5. `HERMES_DESKTOP_TERMINAL` —— 平台提示功能不生效

```ts
// main.ts:13364  —— 桌面端发给终端子进程
env.HERMES_DESKTOP_TERMINAL = '1'
```

```python
# agent/system_prompt.py:154 —— 后端读的是新名
if not is_truthy_value(os.getenv("MATLENS_DESKTOP_TERMINAL")):
```

**影响**：桌面端嵌入的终端不会显示平台提示（"你在 MatLens 桌面端里" 之类的上下文注入）。单测 `tests/agent/test_platform_hint_desktop.py` 是直接设 `MATLENS_DESKTOP_TERMINAL=1` 测的，所以**测试全绿但真机不生效** —— 典型的「测试用新名、生产用旧名」断层。

**建议动作**：桌面端改为 `MATLENS_DESKTOP_TERMINAL`（这个变量只被桌面端自己 spawn 的进程消费，不对外）。

**风险**：低。

### A6. 桌面端与后端命名不一致的环境变量 —— 完整清单

用集合运算把桌面端涉及的 25 个 `HERMES_*` 变量与后端读取的 288 个变量逐一比对，**共 7 处不一致**：

| # | 桌面端用 | 后端读 | 性质 | 建议 |
|---|---|---|---|---|
| 1 | `HERMES_HOME` | `MATLENS_HOME` | **目录分叉**（A2） | 显式传 + 双读 |
| 2 | `HERMES_PORTAL_BASE_URL` | `MATLENS_PORTAL_BASE_URL` | 门户连不上（A3） | 双读 |
| 3 | `HERMES_DASHBOARD_SESSION_TOKEN` | `MATLENS_DASHBOARD_SESSION_TOKEN` | 401（A4） | 直接改 |
| 4 | `HERMES_DESKTOP` | `MATLENS_DESKTOP` | 标记失效（A4） | 直接改 |
| 5 | `HERMES_DESKTOP_READY_FILE` | `MATLENS_DESKTOP_READY_FILE` | 路径丢失（A4） | 直接改 |
| 6 | `HERMES_WEB_DIST` | `MATLENS_WEB_DIST` | 路径错误（A4） | 直接改 |
| 7 | `HERMES_DESKTOP_TERMINAL` | `MATLENS_DESKTOP_TERMINAL` | 提示不生效（A5） | 直接改 |

> 其余 18 个桌面端 `HERMES_*` 变量（`HERMES_DESKTOP_BOOT_FAKE`、`HERMES_DESKTOP_CDP_PORT`、`HERMES_DESKTOP_POOL_MAX` 等）**后端完全不读**，是桌面端自用或仅用于脚本 —— 属于 B/C 类，不影响互操作。

---

### A7. `electron/main.ts` 引用 12 个不存在的导出

**上一轮已修**（提交 `480c6ce`）。这里仅作记录：模块侧改了导出名、调用侧没改，导致 `npm run typecheck` 与 `npm run dev:electron` 在基线上直接失败。

---

### A8. `e2e/fixtures.ts` 的 `MockBackendOptions` 重复声明

**上一轮已修**。interface 声明合并让 TS 不报错，静默把两份字段并到一起。

---

## 2. B 类：可安全改（纯内部标识符）

判断标准：**只在进程内使用，不进协议、不进磁盘路径、不进用户可见文案**。

### B1. `electron/main.ts` 内部的局部变量与内部函数（约 150 处）

形如 `hermesHome` / `hermesPath` / `hermesRoot` / `hermesProcess` / `hermesLog` / `hermesVersion` / `hermesCommand` / `hermesCwd` / `hermesOverride` / `hermesBackendIdentity`，以及 `resolveHermesBackend()` / `unwrapWindowsVenvHermesCommand()` / `pathWithHermesManagedNode()` 等内部函数。

**建议动作**：`hermes*` → `matlens*`（`MatLens*`）。**但不要碰 `HERMES_HOME` / `HERMES_ROOT` 这类全大写常量**（见 C/D 类）。

**风险**：低。编译器能兜住大部分。**注意**：`hermesOverride` / `hermesCommand` 这类局部变量同时也是 `shouldTrustMatLensOverride(hermesOverride)` 的实参 —— 改函数名时容易把实参一起误改，需人工过一遍。

### B2. Python 侧的注释与文档字符串（约 107 处）

分布：`matlens_kit` 19 / `matlens_cli` 58 / `plugins` 22 / `agent` 8。

全部是注释里的「Hermes 原生…」这类表述，例如 `matlens_kit/api/server.py:301` 的「读取 state.db 中该会话的活动消息，用 Hermes 同源的…」。

**建议动作**：直接替换 `Hermes` → `MatLens`。无风险。

### B3. 桌面端 `src/` 里的 1 处残留

`grep` 结果只有 1 条，非 i18n 目录。

### B4. 桌面端 `electron/` 里其它模块的导出名

已在上轮修完（`backend-env` / `backend-health` / `backend-probes` / `remote-lifecycle` / `windows-matlens-path`）。

---

## 3. C 类：需保留（对外契约，改了会破坏互操作）

### C1. URL scheme：`hermes://`

```ts
// apps/desktop/electron/main.ts:14083
const HERMES_PROTOCOL = 'hermes'
```

注册到操作系统（`app.setAsDefaultProtocolClient`），用于 deep link：`hermes://blueprint/...`、`hermes://mcp/install?...`。打包配置里 `build.protocols[].schemes = ["hermes"]`。

**建议动作**：
- **必须保留 `hermes://`**，至少在过渡期
- 同时**新增注册 `matlens://`**，两个 scheme 都监听
- `build.protocols` 里加第二个 scheme
- 深链处理逻辑对两个 scheme 都响应
- 未来某个大版本再考虑弃用 `hermes://`

**风险**：直接改会让用户浏览器里已保存的 `hermes://` 链接全部失效。

### C2. HTTP header：`X-Hermes-Session-Token`

见 A1。后端已不支持，直接改。

### C3. 环境变量：38 个 `HERMES_*`

```
HERMES_HOME (61 处)          HERMES_ROOT (27 处)
HERMES_DASHBOARD_OAUTH_CLIENT_ID (9)  HERMES_DESKTOP_REMOTE_URL (8)
HERMES_DESKTOP_HERMES_ROOT (6)       HERMES_PROTOCOL (5)
HERMES_PORTAL_BASE_URL (5)           HERMES_DASHBOARD_PORTAL_URL (5)
HERMES_WEB_DIST / HERMES_DESKTOP_WEB_DIST / HERMES_DESKTOP_USER_DATA_DIR
HERMES_DESKTOP_SHELL / HERMES_DESKTOP_REMOTE_TOKEN / HERMES_DESKTOP_READY_FILE
HERMES_DESKTOP_IGNORE_EXISTING / HERMES_DESKTOP_HERMES / HERMES_DASHBOARD_SESSION_TOKEN
HERMES_INDEX_URL / HERMES_GIT_BASH_PATH / HERMES_DIAGNOSTICS_BASE_URL
HERMES_DESKTOP_TERMINAL / HERMES_DESKTOP_SKIP_QUIT_CONFIRM / HERMES_DESKTOP_PYTHON
HERMES_DESKTOP_POOL_MAX / HERMES_DESKTOP_POOL_IDLE_MS / HERMES_DESKTOP_PASSWORD_STORE
HERMES_DESKTOP_IS_PACKAGED / HERMES_DESKTOP_DISABLE_GPU / HERMES_DESKTOP_DEV_SERVER
HERMES_DESKTOP_CWD / HERMES_DESKTOP_CHILD_PID / HERMES_DESKTOP_CDP_PORT
HERMES_DESKTOP_BOOT_FAKE / _STEP_MS / _ERROR / HERMES_DESKTOP_APP_NAME
HERMES_DASHBOARD_READY
```

**建议动作**：**全部保留**，不改名。环境变量是用户/脚本/部署环境的对外接口。`HERMES_HOME` 尤其 —— 用户的 config.yaml、API key、记忆数据都在那儿。

> 补充：`HERMES_HOME` 这个名字虽然带旧品牌，但**它就是 MatLens 的配置目录**（`matlens_kit` 已经全面用它了）。改名的收益是「好看」，成本是破坏所有现有部署 —— 不值得。

### C4. 远程协议版本号

`apps/desktop/electron/electron/remote-lifecycle.ts` 的 `PROTOCOL_VERSION = 1` 与握手字段 `protocolVersion`。值是数字，与品牌无关，**保持不动**。

---

## 4. D 类：需迁移（磁盘上的真实路径）

这类改了会**让用户找不到自己的数据**，必须配数据迁移。

### D1. 用户数据目录

```
~/.hermes                                    (macOS / Linux, main.ts:675)
%LOCALAPPDATA%\hermes                        (Windows, main.ts:663)
%LOCALAPPDATA%\hermes-home                   (USER_DATA_OVERRIDE 分支)
~/.hermes/active_profile                     (main.ts:720)
```

### D2. 标记文件与状态文件

```
.hermes-bootstrap-complete                  (main.ts:703, 3674)
.hermes-update-in-progress                   (main.ts:1845)
.hermes-update-result.json                   (main.ts:3838)
```

### D3. venv 内的可执行文件

```ts
// main.ts:2894, 3664
path.join(updateRoot, 'venv', 'bin', 'hermes')
path.join(venvBin, IS_WINDOWS ? 'hermes.exe' : 'hermes')
```

这是 installer 装出来的 CLI 入口文件名。

### D4. Git for Windows 便携版路径

```ts
// main.ts:2384-2385
path.join(localAppData, 'hermes', 'git', 'cmd', 'git.exe')
path.join(localAppData, 'hermes', 'git', 'bin', 'git.exe')
```

### D5. 应用标识与打包产物

```json
// apps/desktop/package.json:181
"appId": "com.nousresearch.hermes",
"productName": "Hermes",
"artifactName": "Hermes-${version}-${os}-${arch}.${ext}",
"executableName": "Hermes",
"protocols": [{ "name": "Hermes Protocol", "schemes": ["hermes"] }]
```

`app.setAppUserModelId('com.nousresearch.hermes')`（main.ts:1081）。

**注意**：改 `appId` 会导致**旧版桌面端与新版无法互相识别**（Windows 的 AppUserModelId、electron-builder 的更新通道、卸载注册表项都跟它绑定）。

### D6. Web 端文案里的 `~/.hermes` 路径（19 个语言文件）

例如 `web/src/i18n/af.ts:383` 的 `configPath: "~/.hermes/config.yaml"`。

**建议动作**：

| 步骤 | 内容 |
|---|---|
| 1 | **只读双读**：启动时优先找 `~/.matlens`，找不到则回落 `~/.hermes`（读）。写一律写到新目录 `~/.matlens` |
| 2 | **一次性迁移**：首次成功读旧目录后，把旧目录内容**移动**（而非复制）到新目录，旧目录留一个 `README_MIGRATED` 说明 |
| 3 | 迁移失败不阻断：捕获异常继续用旧目录，记 warn 日志 |
| 4 | venv 可执行文件、标记文件同理：优先新名，找不到回落旧名 |
| 5 | `appId` / `productName` / `executableName` **单独一个版本做**，并写明确的升级说明 |

**风险**：**高**。这是唯一可能让用户「数据消失」的改动。必须：
- 先做**只读回落**（能读旧的、写新的），观察一个版本
- 再做**主动迁移**
- 迁移必须有失败兜底，且**不删原数据**

### D7. 用户可见文案（约 52 处字符串 + Web 端 19 语言文件 276 处）

桌面端 `main.ts` 里的弹窗标题与消息：

```
'Waiting to start Hermes backend'                    (1235)
title: 'Hermes update'                               (1924)
'Hermes update did not finish'                       (1933)
label: 'Hermes Agent not installed yet; bootstrap required'  (4440)
'Hermes recovery was handed off to Hermes Setup...'  (4475)
'Hermes install was cancelled.'                      (4537)
message: 'Hermes runtime is ready'                    (4614)
title: 'Renewing Hermes Cloud session…'               (7403)
title: 'Sign in to Hermes Cloud'                      (7508)
'Hermes Desktop is already running in another window.' (9760)
message: 'Remote Hermes backend is ready'             (9815)
message: 'Hermes backend is ready. Finalizing...'     (10039)
title: 'Hermes'  (窗口标题, 10218 / 10318 / 11173)
'Hermes is not installed yet'                        (11485)
```

**建议动作**：这一类**风险最低、收益最直接**（用户天天看到）。可以**第一批做**，且与 D1-D6 完全解耦。

**但有个前置依赖**：如果 `Hermes Cloud` 是一个真实的外部服务（不是本地自建），`title: 'Sign in to Hermes Cloud'` 的文案**不能随便改** —— 那是在指代一个具体产品。**需先确认 Nous Portal 与 MatLens 的关系**。

---

## 5. E 类：文档与网站（约 2000 处，单独排期）

| 位置 | 处数 | 说明 |
|---|---|---|
| `website/docs/**` | ~1100 | Docusaurus 文档站（781 个文件被跟踪） |
| `website/i18n/**` | ~800 | 文档的多语言翻译 |
| `website/src/data/userStories.json` | 497 | 用户故事数据 |
| `README*.md`（5 个语言） | ~180 | 根目录 README |
| `optional-skills/**` | ~120 | 技能包里的 Hermes 品牌描述 |
| `apps/desktop/README.md` | 32 | 桌面端说明 |

**建议动作**：**与代码改名完全解耦，单独一个提交/一次 PR**。理由：
- 文档改动量是代码的 10 倍，混在一起会让代码 diff 无法审阅
- 文档需要人工校对术语一致性（不能纯脚本替换）
- `website/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent.md` 这类文件名本身带 hermes，需要单独决策

**注意**：`website/docs/user-guide/configuration.md`（216 处）里很可能有真实的配置项名和路径 —— 那属于 C/D 类，改的时候要挑出来。

---

## 6. 建议的执行顺序

| 批次 | 内容 | 规模 | 风险 | 建议 |
|---|---|---|---|---|
| **0** | **A2**（`MATLENS_HOME` 对齐）+ **A1/A4**（token 链路）+ **A5**（终端标识） | 8 处 | 低 | **立刻做**，已在造成故障 |
| **1** | A3（门户地址双读） | 1 处 | 低 | 跟 0 一起 |
| **2** | D7（桌面端用户文案） | 52 处 | 低 | 顺手做，用户天天看 |
| **3** | B2（Python 注释） | 107 处 | 极低 | 顺手做 |
| **4** | B1（main.ts 内部标识符） | ~150 处 | 低 | 单独一个 commit |
| **5** | C1（新增 `matlens://` scheme） | ~10 处 | 中 | 需要改打包配置 |
| **6** | E（文档网站） | ~2000 处 | 低 | 单独 PR |
| **7** | D1-D5（磁盘路径 + appId） | ~60 处 | **高** | 分两个版本：先只读回落，再主动迁移 |

### 关于批次 0 的说明

这批**不是改名，是修 bug**。判断标准很简单：把 `HERMES_` 换成 `MATLENS_` 之后，**桌面端能不能读到用户自己的配置**。

建议的验证路径（改完后手测一遍）：
1. 在 `~/.matlens/config.yaml`（或桌面端实际用的目录）里配一个 provider
2. 启动桌面端 → 看后端日志读到的是不是同一个 home
3. 桌面端内触发一个需要 token 的端点（如插件列表）→ 确认不是 401
4. 桌面端内开终端 → 确认平台提示出现

**A2 改完可能会「冒出」一批新问题**（比如之前桌面端一直读不到配置，用户以为是自己配错了）。那是好事 —— 那是本来就该生效的东西开始生效了。

---

## 7. 已拍板的决策

| 问题 | 结论 |
|---|---|
| **`Hermes Cloud` 是什么？** | Nous 的外部服务，MatLens **没有自有云**。相关文案与端点保持指向原处，不做产品身份继承。 |
| **`hermes://` 深链兼容期？** | **立即弃用**。协议 canonical scheme 改为 `matlens://`；解析阶段仍兼容 `hermes`，但不再注册旧 scheme。 |
| **appId 改名影响更新通道？** | 桌面端**自行更新**，不依赖 Nous 的更新通道。`appId` 与更新通道无关，留待后续高风险批次。 |
| **`website/` 是不是正式文档站？** | 用途暂不明确，**本轮不动**。 |

---

## 8. 批次 0 的执行结果

批次 0 已完成，落地为一次提交。核心是**修 bug**而非改名：

### A2 — `MATLENS_HOME` 对齐

桌面端原先默认 `%LOCALAPPDATA%\hermes` / `~/.hermes`，后端默认 `~/.matlens` —— 两半读的是**两棵不同的树**，用户的 provider / 记忆 / 会话在桌面端"消失"。现在统一解析到后端定义的同一个目录，且仍会优先采用**实际存在**的旧目录，避免改名吃掉存量数据。

### A1 / A4 — token 链路

后端读 `MATLENS_DASHBOARD_SESSION_TOKEN`，桌面端发 `HERMES_DASHBOARD_SESSION_TOKEN` —— header 名对不上，受保护端点一律 401。现在：

- 后端**同时接受** `X-MatLens-Session-Token` 与 `X-Hermes-Session-Token`，两者都走 `hmac.compare_digest` 常数时间比较，安全性不降；
- 桌面端**同时发送**两个 header；
- 桌面端日志脱敏规则覆盖新旧两个 header 名，避免 token 明文落盘。

### A5 — 终端标识

`MATLENS_DESKTOP` / `MATLENS_DESKTOP_TERMINAL` 统一走兼容层读取。

### 兼容层的落位：一个刻意的设计约束

兼容层最终落在 `matlens_cli/env_compat.py`（**包内**），而非仓库根的顶层模块。

原因是一个启动期崩溃：顶层模块只能通过 editable 安装的 finder 解析，而它的模块映射是**安装时烘焙**的。用户拉取改名后、重装之前跑 CLI，会在启动导入上撞上 `ModuleNotFoundError`；又因为 `matlens_bootstrap` 被每个入口点最先导入、且传递依赖兼容层，整个 CLI 会**起不来** —— 用户连 `matlens update` 都跑不了，正好失去自救手段。

放进包内后，editable finder 通过已映射的 `matlens_cli` 包目录直接找到文件，**落盘即生效，无需重装**。`matlens_bootstrap` 也因此保持零项目依赖（`tui_gateway/entry.py` 与 `slash_worker.py` 是**无保护**导入它的）。

### 顺带修掉的真问题

| 问题 | 影响 |
|---|---|
| `chown hermes:hermes` 残留在容器脚本里 | Dockerfile 已把用户改为 `matlens`，这些 chown 会静默失败（`2>/dev/null \|\| true` 掩盖错误），容器内权限错乱 |
| s6 服务目录 `main-hermes` | 与 Dockerfile 注释、`stage2-hook.sh` 描述不一致；整体拷贝机制下改名安全 |
| `install.ps1` 的运行时覆盖逻辑仍读 `$env:HERMES_HOME` | 与参数默认值（已改 `MATLENS_HOME`）矛盾，同一参数走两套路径 |
| `install.ps1` 默认 `INSTALL_DIR` 用 `hermes-agent` | 与 `install.sh` 的 `matlens-agent` 不一致，两平台装出不同目录名 |
| 写探针 `touch()` 成功但 `unlink()` 失败 | 探针文件残留，且安装目录被误判为只读；已改为 `finally` 清理 |
| `.pytest-cache/` 哨兵文件被提交进 git | 测试缓存进了版本控制；已移出跟踪并加进 `.gitignore` |

### 回归验证中揪出的第二批真问题

批次 0 的改动集涉及 40+ 个 Python 测试文件与整个桌面端。跑完 A/B 对比后，**54 项失败中 0 项由本批次引入** —— 逐项归因如下：

| 失败现象 | 数量 | 归因 |
|---|---|---|
| `RuntimeError: Could not determine home directory` | 22 | 测试用 `@patch.dict(os.environ, clear=True)` 清空了 `USERPROFILE`，Windows 上 `expanduser("~")` 随之失败。**环境性**，基线同样失败 |
| `SystemExit: 2`（`test_cmd_update`） | 4 | Windows 并发实例检测触发 `sys.exit(2)` —— 由并行跑测试时残留的 Python 进程引起。单跑通过（307s） |
| 路径断言不符（`/opt/data/...`、`/opt/homebrew/bin`、`\\` 根） | 6 | Linux 语义断言在 Windows 上必然失败。已用 `git stash` 在基线上复现同样 4 项失败 |
| `Could not determine home directory` 之外的 SSL 错误 | 若干 | `ssl.SSLContext` 在沙箱环境初始化失败，与代码无关 |
| dedup / tilde / safe-cwd 等 | 其余 | 基线逐项复现，确认与本批次无关 |

同时发现并修掉三处**本批次该修但没修**的问题：

| 问题 | 影响 |
|---|---|
| `matlens-agent.nousresearch.com` 域名在 DNS 上不存在（`curl` 返回 000） | 改名把上游文档站域名一并改了，导致桌面端「在远程安装」、Skills Hub、Discord/Slack 引导链接、模型目录清单全部指向死链。真实上游 `hermes-agent.nousresearch.com` 各路径均返回 200，已按「真实上游引用保持指向原处」的既定原则回退，涉及 13 个文件 |
| `tools/skills_hub.py` 定义 `HERMES_INDEX_URL` 却引用 `MATLENS_INDEX_URL` | `NameError` —— 集中式索引拉取与陈旧缓存回落两条路径直接崩。已改为 canonical 名并保留旧名别名 |
| 模型目录回落链的分支名写成 `/main/` | 远端默认分支是 `master`（`/main/` 返回 404，`/master/` 返回 200），回落链实际指向死链。已修正测试断言 |

### 补齐的路径一致性（A2 的最后一环）

批次 0 的目标是让桌面端与 CLI 装到**同一棵目录树**上。验证时发现三处仍不自洽：

| 问题 | 影响 | 修法 |
|---|---|---|
| 桌面端 `ACTIVE_HERMES_ROOT` 只认 `hermes-agent`，而 `install.sh` / `install.ps1` 装到 `matlens-agent` | **新装用户桌面端找不到安装** —— 恰好是批次 0 想解决的那类"数据消失"问题 | 改为优先 `matlens-agent`，回落 `hermes-agent`（存量安装继续可用），与 `resolveMatLensHome()` 对 home 根目录的"优先 canonical、接受 legacy"策略同构 |
| `install.ps1` 参数默认值与运行时覆盖逻辑走两套路径 | 传参与默认落到不同目录 | 三处（参数默认值 / 运行时覆盖 / 完成提示）统一为 `$MATLENS_HOME\matlens-agent`，`HERMES_HOME` 回落时仍用 `hermes-agent` 保住存量 |
| `install.ps1` 的 extras 正则仍匹配 `hermes-agent[...]` | 项目名已是 `matlens-agent`，`[all]` extras 解析**静默返回空**，可选依赖（cron/pty/mcp/acp 等 9 项）装不上 | 正则改为 `matlens-agent[...]`，已验证解析出 9 项 |

### 仍未覆盖的已知缺口

- **FHS 布局**：Linux root 下 `install.sh` 装到 `/usr/local/lib/matlens-agent`，桌面端只在 `$HERMES_HOME` 下找。基线即如此（非本轮引入），本轮不扩大范围。
- **`website/` 文档**：按用户决定本轮**不改名**。但其中的 `matlens-agent.nousresearch.com` 死链属功能性问题（DNS 不解析），已单独修掉 —— 只替换域名，不动任何文案与结构。

---

## 9. 尚未处理

- **C1 打包配置**（`appId` / `productName`）—— 高风险批次
- **D1-D5 磁盘路径迁移** —— 高风险批次，需分两个版本：先只读回落，再主动迁移
- **E 文档网站**（`website/`）—— 单独 PR

