#!/usr/bin/env bash
# 服务器健康体检 —— 通过 SSH 在 MatLens 部署机上做只读诊断。
#
#   用法: scripts/server-health.sh [ssh目标]
#   默认: aliyun-matlens
#
# 全部为只读检查，不改任何东西。用于部署后确认服务状态，以及排查
# 「HTTP 502 / SSH 超时」这类假死事故。
#
# 退出码: 0 = 全部正常, 1 = 有 WARN, 2 = 有 FAIL

set -uo pipefail

TARGET="${1:-aliyun-matlens}"
SCRIPT=$(cat <<'EOS'
set +e
echo "===== 1. 系统 ====="
uptime
echo "--- 内核 OOM 记录（关键：无输出说明没发生过 OOM）---"
dmesg -T 2>/dev/null | grep -iE "out of memory|oom-kill|killed process" | tail -10 || echo "(dmesg 无权限或无 OOM 记录)"

echo
echo "===== 2. 内存 ====="
free -m
echo "--- swap ---"
swapon --show 2>/dev/null || echo "(未启用 swap)"
cat /proc/meminfo | grep -E "MemTotal|MemAvailable|SwapTotal|SwapFree"

echo
echo "===== 3. 磁盘 ====="
df -h / /tmp 2>/dev/null | head -5

echo
echo "===== 4. MatLens 进程（按内存排序）---"
ps -eo pid,ppid,rss,etime,cmd --sort=-rss 2>/dev/null | grep -iE "matlens|uvicorn|gunicorn|python" | grep -v grep | head -12
echo "--- MatLens 进程总数 ---"
pgrep -fc "matlens" 2>/dev/null || echo 0

echo
echo "===== 5. 监听端口 ====="
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E "LISTEN" | head -15

echo
echo "===== 6. 服务管理 ====="
for svc in matlens matlens-dashboard matlens-setup; do
  if command -v systemctl >/dev/null 2>&1; then
    st=$(systemctl is-active "$svc" 2>/dev/null)
    [ -n "$st" ] && echo "  $svc: $st"
  fi
done
echo "--- 监听 8321 的进程 ---"
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep 8321 || echo "  (8321 未监听)"

echo
echo "===== 7. 部署仓库状态 ====="
for d in /opt/matlens /srv/matlens /root/matlens /home/*/matlens /opt/MatLens; do
  if [ -d "$d/.git" ]; then
    echo "  仓库: $d"
    git -C "$d" log --oneline -3 2>/dev/null | sed 's/^/    /'
    git -C "$d" status -sb 2>/dev/null | head -3 | sed 's/^/    /'
    break
  fi
done

echo
echo "===== 8. 最近日志 ====="
if command -v journalctl >/dev/null 2>&1; then
  echo "--- matlens / uvicorn 最近 30 行 ---"
  journalctl --no-pager -n 30 -u matlens 2>/dev/null | tail -30
  journalctl --no-pager -n 15 2>/dev/null | grep -iE "matlens|oom|error" | tail -15
fi
EOS
)

echo "### 目标: $TARGET"
ssh -o ConnectTimeout=15 -o BatchMode=yes "$TARGET" "$SCRIPT" 2>&1
rc=$?

if [ $rc -ne 0 ]; then
    echo
    echo "### SSH 连接失败（退出码 $rc）—— 服务器可能仍未恢复或网络不通"
    echo "### 排查: ping \$TARGET / 阿里云控制台看实例状态"
fi
exit $rc
