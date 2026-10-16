# -*- coding: utf-8 -*-
"""生成结果守卫：识别「API 报错文本被当成正文返回」的情况。

背景（真实事故）：上游模型欠费/鉴权失败时，agent 把错误提示原样塞进
final_response（而非抛异常），runner 会把它当成正常正文写进 stages_json，
**静默覆盖用户已有的数万字正文**。402/401/429 等场景都会中招。

本模块提供 is_error_text() 供 papers_api 的 runner 在落库前拦截，
命中即抛异常 → 引擎走 error 分支，保留原正文不动。

设计取向：宁可漏判（多写一次）也不误判（正文被覆盖）——
只匹配高置信度的错误特征串，不做语义猜测。
"""
from __future__ import annotations

import re
from typing import Optional

#: 高置信度错误标记（任一命中即判定为错误文本）
_ERROR_MARKERS = (
    "billing, credits, or account entitlement is exhausted",
    "insufficient balance",
    "insufficient_balance",
    "incorrect api key",
    "invalid api key",
    "authentication_error",
    "permission_error",
    "rate_limit_error",
    "context_length_exceeded",
    "billing or credits exhausted",
    "余额不足",
    "额度不足",
    "余额耗尽",
)

#: HTTP 状态码形态：HTTP 4xx / 5xx
_HTTP_ERR = re.compile(r"\bHTTP\s+([45]\d{2})\b")
#: litellm 风格：Error code: 402
_LITELLM_ERR = re.compile(r"\bError code:\s*([45]\d{2})\b")
#: openai 风格：error code: 402
_OPENAI_ERR = re.compile(r"\berror\s+code:\s*([45]\d{2})\b")


def is_error_text(text: Optional[str]) -> bool:
    """判断一段「生成结果」是否其实是上游 API 的错误提示文本。"""
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    low = t.lower()

    # 标记串命中
    for m in _ERROR_MARKERS:
        if m in low:
            return True

    # 短文本 + HTTP 错误码：正常论文正文不会这么短
    if len(t) < 600:
        for pat in (_HTTP_ERR, _LITELLM_ERR, _OPENAI_ERR):
            if pat.search(t):
                return True

    # 极短的纯错误提示（无正文特征）
    if len(t) < 200 and ("please add credits" in low or "top_up" in low or "switch providers" in low):
        return True

    return False


def error_summary(text: Optional[str]) -> str:
    """从错误文本里抽出可读摘要（用于 error 字段/SSE 前端展示）。"""
    if not text:
        return "上游模型调用失败"
    t = text.strip()
    m = _HTTP_ERR.search(t) or _LITELLM_ERR.search(t) or _OPENAI_ERR.search(t)
    first_line = t.splitlines()[0].strip() if t else ""
    if m:
        return f"HTTP {m.group(1)}：{first_line[:160]}"
    return first_line[:200] or "上游模型调用失败"


def ensure_not_error(text: Optional[str], stage: str = "") -> None:
    """落库前守卫：文本是错误提示则抛异常，让引擎走 error 分支保住原正文。"""
    if is_error_text(text):
        where = f"[{stage}] " if stage else ""
        raise RuntimeError(f"{where}上游模型返回错误而非正文：{error_summary(text)}")