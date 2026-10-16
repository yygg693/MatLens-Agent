# MatLens Web 服务 —— Windows 生产化部署指南（S5）

本文件说明如何把 MatLens FastAPI 后端注册为 Windows 开机自启服务，以及对外暴露前的安全开关。

## 0. 启动命令（唯一入口）

```
D:\MatLens\.venv\Scripts\python.exe -m matlens_kit.api.server --port 7896
```

- 工作目录建议设为项目根：`D:\MatLens`
- 配置全部读 `%USERPROFILE%\.matlens\config.yaml` 的 `server:` 段：
  - `host`（默认 `127.0.0.1`）、`port`（默认 `7896`）
  - `auth_enabled`（默认 `false`）、`auth_token`（默认空）
  - `allowed_origins`（默认 `[]`，空=同源）
- `--host` / `--port` 命令行参数会覆盖 config 里的值；不传则用 config 默认值。
- 启动时自动做三件后台事：崩溃恢复 stuck 论文步骤、预热 agent、备份
  `papers.db` / `state.db` 到 `~/.matlens/backups/YYYYMMDD_HHMMSS/`（只留最近 7 份）。

## 1. 安全红线：对外暴露前必须开鉴权

默认 `host: 127.0.0.1` 只监听本机，**不需要 token**，开箱即用。

一旦要把 `host` 改成 `0.0.0.0`（或局域网/公网可达），**必须**先在
`%USERPROFILE%\.matlens\config.yaml` 打开鉴权，否则任何人都能调用你的 `/api/*`：

```yaml
server:
  host: 0.0.0.0
  port: 7896
  auth_enabled: true
  auth_token: "改成一段足够长的随机串"   # 留空则启动时随机生成并打印到控制台
  allowed_origins:
    - "http://192.168.x.x:7896"        # 跨域访问时才需要填；同源访问留空 []
```

- `auth_enabled: true` 且 `auth_token` 为空时，服务启动会在控制台打印
  `[auth] MatLens token: <随机串>  (http://<host>:<port>)`。
- 开启后，除 `/`、`/api/health`、静态资源（`/js/*`、`/assets/*`、index.html 等）外，
  所有 `/api/*` 都要求请求头 `Authorization: Bearer <token>`，否则返回
  `401 {"ok":false,"error":"unauthorized"}`。
- 前端会自动从 `localStorage.matlens_token` 读 token；首次 401 会弹出 token 输入框，
  输入后保存并重放请求。

## 2. 方式 A：用 NSSM 注册为 Windows 服务（推荐）

NSSM（Non-Sucking Service Manager）可把任意控制台程序包成开机自启服务。

1. 下载 NSSM：https://nssm.cc/download ，解压后把 `nssm.exe`（按系统选 win64）
   放进 `C:\Windows\System32\` 或加入 PATH。

2. 管理员身份打开 PowerShell，执行安装：

```powershell
nssm install MatLensApi `
  "D:\MatLens\.venv\Scripts\python.exe" `
  "-m matlens_kit.api.server --port 7896"
```

3. 设置工作目录与日志（强烈建议，否则相对路径和控制台日志丢失）：

```powershell
nssm set MatLensApi AppDirectory "D:\MatLens"
nssm set MatLensApi AppStdout    "D:\MatLens\.matlens_runtime\out.log"
nssm set MatLensApi AppStderr    "D:\MatLens\.matlens_runtime\err.log"
nssm set MatLensApi AppRotateFiles 1
nssm set MatLensApi AppRotateBytes 10485760
```

4. 启动 / 常用管理命令：

```powershell
nssm start   MatLensApi     # 启动
nssm stop    MatLensApi     # 停止
nssm restart  MatLensApi    # 重启（改完 config.yaml 后执行）
nssm status   MatLensApi    # 查状态
nssm remove   MatLensApi confirm   # 卸载服务
```

- 开机自启由 SCM 自动管理，无需登录到桌面。
- 若改了 `config.yaml`，执行 `nssm restart MatLensApi` 让新配置生效。
- 健康检查：浏览器或 `curl http://127.0.0.1:7896/api/health`，应返回
  `{"ok":true,...}` 且带 `db` / `agent_ready` / `errors_warn` 字段。

## 3. 方式 B：用任务计划程序（schtasks）——不想装 NSSM 时

以「用户登录时」自启为例（无需管理员即可创建；要开机即启且无登录态则用 SYSTEM）：

```powershell
schtasks /Create /TN "MatLensApi" /SC ONLOGON /RL HIGHEST /TR ^
  "\"D:\MatLens\.venv\Scripts\python.exe\" -m matlens_kit.api.server --port 7896" ^
  /SD 01/01/2026
```

- `/SC ONLOGON`：登录后启动；要真正开机自启（不登录也跑）用 `/SC ONSTART`，
  且需管理员运行 schtasks，任务以 SYSTEM 身份执行。
- 立即触发一次：`schtasks /Run /TN "MatLensApi"`
- 停止：任务计划没有「停止单进程」的原语，按端口杀进程：
  ```powershell
  Get-NetTCPConnection -LocalPort 7896 -State Listen |
    Select-Object -Expand OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force }
  ```
- 删除任务：`schtasks /Delete /TN "MatLensApi" /F`

> schtasks 不如 NSSM 健壮：崩溃不会自动拉起、控制台日志不落盘。
> 长期运行优先用方式 A。

## 4. 验证清单

部署后逐项确认：

- [ ] `curl http://127.0.0.1:7896/api/health` 返回 200，含
      `db.papers_db_kb` / `db.state_db_kb` / `db.graph_json_kb` / `agent_ready` /
      `errors_warn`。
- [ ] 浏览器打开 `http://127.0.0.1:7896/` 首页 200。
- [ ] `~/.matlens/backups/` 下出现一个 `YYYYMMDD_HHMMSS/` 目录，内含
      `papers.db`、`state.db`（及 WAL 侧车）。
- [ ] 若绑 `0.0.0.0`：`curl http://<host>:7896/api/papers`（不带 token）应得
      `401 {"ok":false,"error":"unauthorized"}`；带
      `curl -H "Authorization: Bearer <token>" http://<host>:7896/api/papers` 得 200。
- [ ] 本机 `127.0.0.1` 访问仍正常（auth 开启后本机也需带 token，前端浮层会提示）。
