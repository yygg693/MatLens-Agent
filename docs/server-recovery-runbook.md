# MatLens 部署机恢复预案

适用对象：`8.148.23.67`（阿里云，2 核 1G，Alibaba Cloud Linux 3）
部署端口：`8321`（nginx 反代到 MatLens 后端）

---

## 一、2026-11-07 事故记录

push 13 个提交后，服务器逐步失联：

| 阶段 | 现象 | 含义 |
|---|---|---|
| 1 | HTTP 502 `upstream connect failed: connection timed out` | nginx 活着，后端连不上 |
| 2 | SSH 22 端口超时 | sshd 也调度不动 |
| 3 | 全端口不通、ping 100% 丢包 | 系统彻底僵死 |

**判断：1G 内存机器 OOM 后系统假死。** push 触发部署（git pull + 重启服务），
新旧 MatLens 进程短暂并存 —— 每个进程要加载 42 个工具 + 43 个延后加载的 MCP
工具 + 长 system prompt，瞬时内存吃穿。

**与代码改动无关**，已核实：

```bash
# 服务端运行路径完全没被本轮改动触及
git diff --name-only <base>..HEAD | grep -E "^matlens_kit/|^matlens_cli/web_server|^agent/"
# → 空
```

服务端只 import `matlens_cli.config` / `matlens_cli.env_compat`，
**不 import `matlens_cli.main`**（本轮只给 main.py 加了 `migrate` 子命令）。

---

## 二、恢复步骤

### 步骤 1：控制台重启（必须手动）

阿里云控制台 → ECS → 该实例 → **重启**。若重启后仍不响应，
改用「停止」→ 等待完全停止 → 「启动」。

> 实例若显示「已停止/欠费释放」，先处理欠费或实名认证问题。

### 步骤 2：跑体检脚本

```bash
scripts/server-health.sh
```

重点看三处：
1. **第 1 节 OOM 记录** —— 有输出就坐实了 OOM
2. **第 2 节 swap** —— `SwapTotal` 为 0 就是没 swap（问题根源之一）
3. **第 5/6 节端口与服务** —— 8321 是否有人监听

### 步骤 3：加 swap（1G 机器强烈建议）

```bash
fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab    # 重启后仍生效
free -h
```

### 步骤 4：拉代码并重启服务

```bash
cd <部署仓库路径>          # 体检脚本第 7 节会告诉你路径
git pull
git log --oneline -1       # 确认是 d2ec2fc
```

服务怎么起的，以服务器上实际的为准（systemd unit / 脚本 / supervisor）。
**关键：先停旧进程，再起新进程**，不要让两者并存。

```bash
# systemd 方式
systemctl stop  matlens 2>/dev/null
systemctl start matlens 2>/dev/null
systemctl status matlens --no-pager -n 20
```

### 步骤 5：验证

```bash
curl -s -o /dev/null -w "8321: HTTP %{http_code}\n" http://127.0.0.1:8321/
free -h                                    # 内存有富余
systemctl is-active matlens                # active
```

再从本地验证外部可达：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://8.148.23.67:8321/
```

---

## 三、防复发

| 措施 | 做法 |
|---|---|
| **加 swap** | 至少 2G（步骤 3）。1G 物理内存跑两个 agent 进程必须有 swap 兜底 |
| **部署改为串行** | 停 → 起，不要并存。post-receive hook 或 cron 脚本都要检查 |
| **部署前检查内存** | `free -m` 剩余不足 300M 时跳过部署，等回收 |
| **限制单进程内存** | 给 systemd unit 加 `MemoryMax=600M`，超了让它自己崩而不是拖垮整机 |
| **日志落盘** | `journalctl` 已经能看到，但确认 `dmesg` 没被 `clear` 掉 |
| **监控** | 至少监控 8321 可用性 + 内存水位；这机器没有健康检查就是瞎跑 |

---

## 四、相关文件

- `scripts/server-health.sh` —— 只读体检脚本（本 PR 新增）
- `docs/rename-audit-hermes-to-matlens.md` —— 改名审计记录，§10.9 是刻意保留清单
