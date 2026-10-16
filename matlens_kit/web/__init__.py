"""MatLens · 网页抓取层（合规优先的公开内容获取）。"""

from matlens_kit.web.web_fetcher import (
    BLOCKED_SITES,
    capabilities,
    check_proxy,
    extract_meta,
    extract_text,
    fetch,
    fetch_cached,
    fetch_many,
    privacy_report,
    REFUSED_TECHNIQUES,
    USER_AGENT,
)

__all__ = [
    "BLOCKED_SITES", "capabilities", "check_proxy", "extract_meta", "extract_text", "fetch",
    "fetch_cached", "fetch_many", "privacy_report", "REFUSED_TECHNIQUES", "USER_AGENT",
]
