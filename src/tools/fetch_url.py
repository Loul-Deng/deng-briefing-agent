"""fetch_url: HTML to truncated plain text. No PDF parsing in v1."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from config import load_config
from registry import ToolRegistry

_SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe"}
_USER_AGENT = "DENG-briefing-agent/0.1 (+https://localhost; research briefing)"


class _TextExtractor(HTMLParser):
    """把 HTML 剥成纯文本。跳过 script/style，块级标签换成换行。"""

    def __init__(self) -> None:
        """初始化提取器。"""
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """遇到开始标签：跳过黑名单标签，块级标签插入换行。"""
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """遇到结束标签：如果正在跳过 script/style，计数减一。"""
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        """收集可见文本节点。"""
        if self._skip:
            return
        text = data.strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        """合并并压缩空白，得到最终纯文本。"""
        joined = " ".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", joined)).strip()


def _looks_like_pdf(url: str, content_type: str) -> bool:
    """根据 URL 后缀或 Content-Type 判断是不是 PDF（v1 不解析）。"""
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return True
    return "application/pdf" in (content_type or "").lower()


def fetch_url(url: str) -> str:
    """抓取 http(s) 页面，返回截断后的纯文本 JSON。GitHub HTML 超时会提示改用 raw URL。"""
    if not url or not str(url).strip():
        return json.dumps({"error": "url is empty"}, ensure_ascii=False)
    url = str(url).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return json.dumps({"error": "only http/https URLs are allowed"}, ensure_ascii=False)

    web = (load_config().get("web") or {})
    timeout = float(web.get("fetch_timeout_sec") or 20)
    max_chars = int(web.get("fetch_max_chars") or 8000)

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": _USER_AGENT}) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        hint = ""
        host = (parsed.hostname or "").lower()
        if "github.com" in host and "/blob/" not in url:
            hint = " GitHub HTML pages often time out; retry the raw file URL, e.g. https://raw.githubusercontent.com/owner/repo/main/README.md"
        return json.dumps({"error": f"request failed: {exc}.{hint}", "url": url}, ensure_ascii=False)

    content_type = response.headers.get("content-type", "")
    final_url = str(response.url)
    if _looks_like_pdf(final_url, content_type):
        return json.dumps(
            {
                "error": "PDF is not supported in v1. Fetch the HTML abstract page instead (e.g. arXiv abs/).",
                "url": final_url,
            },
            ensure_ascii=False,
        )

    if response.status_code >= 400:
        return json.dumps(
            {"error": f"HTTP {response.status_code}", "url": final_url},
            ensure_ascii=False,
        )

    html = response.text
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
        text = extractor.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    return json.dumps(
        {
            "ok": True,
            "url": final_url,
            "status": response.status_code,
            "truncated": truncated,
            "text": text,
        },
        ensure_ascii=False,
    )


def register(registry: ToolRegistry) -> None:
    """把 fetch_url 登记进注册表。"""
    registry.register(
        name="fetch_url",
        description=(
            "Fetch an http(s) URL and return truncated plain text. "
            "Use this to read paper abstracts, GitHub README pages, or news. "
            "Do not fetch PDFs; use the HTML abstract page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full http or https URL to fetch.",
                }
            },
            "required": ["url"],
        },
        handler=fetch_url,
    )
