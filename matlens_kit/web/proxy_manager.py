# -*- coding: utf-8 -*-
"""MatLens · 代理配置与出口 IP 轮换（network 段）。

## 为什么是 Tor 而不是随机代理池

用户要的是「自动换 IP + 手动换」。实现上必须先回答一个问题：**换谁的 IP？**

- ❌ **随机免费代理池**：那些公开代理的运营者能看见你所有流量的明文，日志被
  倒卖是常态。费力隐藏身份，却交给了随机遇到的陌生人 —— 与隐私目标**相反**。
  而且频繁换 IP 会打出「同一客户端在轮换」的规律，更易被聚类关联。
- ✅ **Tor**：出口由 Tor 网络（志愿者中继）分配，客户端不信任但**可验证**
  链路加密；**NEWNYM 信号是 Tor 协议自带的标准动作**，专门用来请求新出口，
  这正是用户想要的「自动换 IP」，且来源可信。

所以本模块**只对接 Tor ControlPort**，不实现随机代理池轮换。

## 换 IP 的三种触发时机

1. **手动**：用户点「立即换 IP」
2. **定时**：距上次换 IP 超过 ``rotate_every`` 秒
3. **计数**：本次会话累计请求超过 ``rotate_max_requests`` 次

计数器是**进程内**的，重启即归零 —— 磁盘上不记录「我们换过多少次 IP」，
这本身就是一条不该留的痕迹。

## Tor ControlPort 协议（最小实现）

Tor 开启 ``ControlPort`` 后可用明文认证协议发命令::

    AUTHENTICATE            -> 250 OK
    SIGNAL NEWNYM           -> 250 OK      # 请求新出口（Tor 需满足最小流间隔）
    GETINFO circuit-status  -> 250 OK ...  # 可选：验证是否真的换了线路

要点：
- **认证**：优先用 ``CookieAuthenticationFile`` 生成的 cookie（Tor 默认，推荐）；
  没有 cookie 文件时回退 ``AUTHENTICATE "password"``。
- **NEWNYM 有最小间隔**：Tor 对同一流量的换线路有速率限制（约 10 秒），
  太快会被忽略。所以这里做了节流，并把「Tor 未换成功」如实报告，
  **不假装成功**。
"""
from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any, Dict, Optional

# ────────────────────────────────────────────────────────────
# 运行时状态（进程内，不落盘）
# ────────────────────────────────────────────────────────────
_state_lock = threading.Lock()
_requests_since_rotate = 0
_last_rotate_ts = 0.0        # 0 = 从未换过
_last_rotate_result: Dict[str, Any] = {}

#: Tor 对同一流量的 NEWNYM 有最小间隔（约 10s），早于此不发，避免无效请求
NEWNYM_MIN_INTERVAL = 11.0

SUPPORTED_SCHEMES = ("socks5h", "socks5", "socks4", "http", "https")


# ────────────────────────────────────────────────────────────
# 配置读取（settings_store 优先，其次环境变量）
# ────────────────────────────────────────────────────────────
def _load_network_section() -> Dict[str, Any]:
    """读 network 段配置。

    注：这里原本为绕过 settings_store 的路径不一致 bug 而写了「读两处」的兜底，
    该 bug 已于 2026-10-15 在 settings_store 侧修复（统一到
    ``matlens_cli.config.get_matlens_home()``，并迁移了旧配置 + 兼容读旧路径）。
    因此本函数回到单一来源，不再重复实现路径逻辑 ——
    路径只有一个事实来源，才不会再次分叉。
    """
    try:
        from matlens_kit.settings_store import get_section

        got = get_section("network")
        return dict(got) if isinstance(got, dict) else {}
    except Exception:
        return {}


def get_config() -> Dict[str, Any]:
    """读取网络/代理配置。

    优先级：设置页已保存的配置 > 环境变量 MATLENS_WEB_PROXY > 默认值。
    设置页开关关闭时**不**使用任何代理（明确关闭，胜过隐式回退）。
    """
    cfg: Dict[str, Any] = {
        "enabled": False,
        "url": "",
        "tor_control": "127.0.0.1:9051",
        "rotate_enabled": False,
        "rotate_every": 30,
        "rotate_max_requests": 50,
        "source": "default",
    }
    sec = _load_network_section()
    if sec:
        cfg.update({
            "enabled": bool(sec.get("proxy_enabled")),
            "url": str(sec.get("proxy_url") or "").strip(),
            "tor_control": str(sec.get("tor_control") or "").strip() or cfg["tor_control"],
            "rotate_enabled": bool(sec.get("rotate_enabled")),
            "rotate_every": _as_int(sec.get("rotate_every"), 30),
            "rotate_max_requests": _as_int(sec.get("rotate_max_requests"), 50),
            "source": "settings",
        })
    # 只有「设置页从未配置过 network 段」时才用环境变量。
    # 若用户已在设置页明确关掉开关，就以设置页为准 ——
    # 否则会出现「界面上关了，环境变量还在偷偷走代理」这种反直觉行为。
    if not sec:
        env = (os.environ.get("MATLENS_WEB_PROXY") or "").strip()
        if env:
            cfg.update({"enabled": True, "url": env, "source": "env"})
    return cfg


def _as_int(v: Any, default: int) -> int:
    try:
        n = int(v)
        return n if n >= 0 else default
    except (TypeError, ValueError):
        return default


def effective_proxy() -> str:
    """当前应使用的代理地址；未启用返回空串（= 直连）。"""
    cfg = get_config()
    if not cfg.get("enabled"):
        return ""
    url = (cfg.get("url") or "").strip()
    if not url:
        return ""
    # 没写协议时默认按 socks5h 理解（Tor 默认是 socks，且 h 能防 DNS 泄露）
    if "://" not in url:
        url = "socks5h://" + url.lstrip("/")
    return url


# ────────────────────────────────────────────────────────────
# Tor ControlPort 客户端
# ────────────────────────────────────────────────────────────
class TorControlError(RuntimeError):
    """与 Tor 控制端口通信失败。"""


def _cookie_path() -> str:
    """Tor 的认证 cookie 路径。

    优先读环境变量（Tor Browser 通常设 TOR_CONTROL_COOKIE_AUTH_FILE），
    再找常见默认路径。Tor 默认用 cookie 认证，密码认证需要显式配置。
    """
    env = (os.environ.get("TOR_CONTROL_COOKIE_AUTH_FILE") or "").strip()
    if env and os.path.exists(env):
        return env
    if os.name == "nt":
        home = os.environ.get("APPDATA") or os.path.expanduser("~")
        cand = os.path.join(home, "Tor", "Browser", "TorBrowser", "Data",
                            "control_auth_cookie")
        if os.path.exists(cand):
            return cand
    for cand in (os.path.expanduser("~/.tor/control_auth_cookie"),
                 "/var/lib/tor/control_auth_cookie",
                 "/run/tor/control_auth_cookie"):
        if os.path.exists(cand):
            return cand
    return ""


def _read_cookie(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


class _TorConn:
    """极简 Tor ControlPort 连接。"""

    def __init__(self, addr: str, timeout: float = 8.0):
        host, _, port = addr.partition(":")
        self.timeout = timeout
        self.sock = socket.create_connection((host.strip() or "127.0.0.1",
                                              int(port or 9051)), timeout=timeout)
        self.buf = b""

    def readline(self) -> str:
        while b"\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise TorControlError("Tor 控制端口意外关闭（Tor 是否在运行并开启 ControlPort？）")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line.decode("utf-8", "replace")

    def read_reply(self) -> str:
        """读取一个完整回复（含多行的 `250-` 续行）。"""
        lines = [self.readline()]
        while lines[-1][:4] in ("250-", "101-"):
            lines.append(self.readline())
        return "\n".join(lines)

    def cmd(self, c: str) -> str:
        self.sock.sendall((c + "\r\n").encode("utf-8"))
        return self.read_reply()

    def authenticate(self) -> None:
        cp = _cookie_path()
        if cp:
            cookie = _read_cookie(cp)
            # AUTHENTICATE <hex>
            r = self.cmd("AUTHENTICATE " + cookie.hex())
        else:
            pw = (os.environ.get("TOR_CONTROL_PASSWORD") or "").strip()
            r = self.cmd(f'AUTHENTICATE "{pw}"' if pw else "AUTHENTICATE")
        if not r.startswith("250"):
            first = r.split("\n")[0][:120]
            raise TorControlError(
                f"Tor 认证失败：{first}。"
                "请确认已开启 ControlPort，且 cookie 文件路径可读"
                "（或设置环境变量 TOR_CONTROL_PASSWORD）。")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


def tor_newnym(timeout: float = 8.0, addr: str = "") -> Dict[str, Any]:
    """请求 Tor 分配新出口 IP（NEWNYM）。

    返回如实反映结果 —— **失败就说失败**，不假装成功。
    """
    cfg = get_config()
    addr = (addr or cfg.get("tor_control") or "127.0.0.1:9051").strip()
    t0 = time.time()
    global _last_rotate_ts, _last_rotate_result
    with _state_lock:
        elapsed = time.time() - _last_rotate_ts if _last_rotate_ts else 999.0
    if _last_rotate_ts and elapsed < NEWNYM_MIN_INTERVAL:
        return {
            "ok": False, "skipped": True,
            "reason": f"距上次换 IP 仅 {elapsed:.0f}s，Tor 要求至少 "
                      f"{NEWNYM_MIN_INTERVAL:.0f}s 间隔（连续点没用）",
            "retry_after_s": int(NEWNYM_MIN_INTERVAL - elapsed),
        }

    conn = None
    try:
        conn = _TorConn(addr, timeout)
        conn.authenticate()
        r = conn.cmd("SIGNAL NEWNYM")
        ok = r.startswith("250")
        # NEWNYM 是异步生效的：这里只能确认「已接受」，真正的换线路要看出口 IP
        result = {
            "ok": ok,
            "control": addr,
            "reply": r.split("\n")[0][:120],
            "note": ("Tor 已接受信号。出口 IP 通常在数秒内切换，"
                     "点「测试连接」可确认是否真的变了。"
                     if ok else "Tor 拒绝了信号"),
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
        with _state_lock:
            if ok:
                _last_rotate_ts = time.time()
                _requests_since_rotate = 0
            _last_rotate_result = dict(result)
        return result
    except TorControlError as e:
        result = {
            "ok": False, "control": addr,
            "reason": str(e)[:200],
            "advice": ("需在 torrc 开启 ControlPort（常见：ControlPort 9051、"
                       "CookieAuthenticationFile control_auth_cookie），"
                       "并在隐私设置里确认端口一致。"),
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
        with _state_lock:
            _last_rotate_result = dict(result)
        return result
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "control": addr,
                  "reason": f"{type(e).__name__}: {e}"[:200],
                  "advice": "确认 Tor 在运行，且控制端口未被防火墙拦截",
                  "elapsed_ms": int((time.time() - t0) * 1000)}
        with _state_lock:
            _last_rotate_result = dict(result)
        return result
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────────
# 自动轮换触发
# ────────────────────────────────────────────────────────────
def note_request() -> None:
    """每发起一次抓取调用一次，供计数器使用。"""
    global _requests_since_rotate
    with _state_lock:
        _requests_since_rotate += 1


def rotate_status() -> Dict[str, Any]:
    """当前轮换状态（供 UI 展示）。"""
    cfg = get_config()
    with _state_lock:
        reqs = _requests_since_rotate
        last = _last_rotate_ts
        last_res = dict(_last_rotate_result)
    since = int(time.time() - last) if last else -1
    return {
        "rotate_enabled": cfg["rotate_enabled"],
        "rotate_every": cfg["rotate_every"],
        "rotate_max_requests": cfg["rotate_max_requests"],
        "requests_since_rotate": reqs,
        "seconds_since_rotate": since,
        "tor_needed": True,
        "note": ("自动轮换依赖 Tor 的 NEWNYM 信号；未运行 Tor 时自动轮换不会生效，"
                 "界面会明确提示，不会假装换了 IP。"),
        "last_result": last_res,
        "due": _should_rotate()[0],
        "due_reason": _should_rotate()[1],
    }


def _should_rotate() -> tuple:
    """判断是否该换 IP，返回 (是否该换, 原因)。"""
    cfg = get_config()
    if not cfg["rotate_enabled"]:
        return False, "自动换 IP 未开启"
    url = effective_proxy()
    if not url:
        return False, "未启用代理，无从换起"
    with _state_lock:
        reqs = _requests_since_rotate
        last = _last_rotate_ts
    mx = int(cfg["rotate_max_requests"] or 0)
    if mx > 0 and reqs >= mx:
        return True, f"本次已请求 {reqs} 次，达到上限 {mx}"
    ev = int(cfg["rotate_every"] or 0)
    if ev > 0 and last and (time.time() - last) >= ev:
        return True, f"距上次换 IP 已超过 {ev}s"
    return False, "未到轮换条件"


def maybe_rotate() -> Optional[Dict[str, Any]]:
    """抓取前调用：达到条件则自动换 IP。返回结果（未触发为 None）。"""
    due, _reason = _should_rotate()
    if not due:
        return None
    return tor_newnym()
