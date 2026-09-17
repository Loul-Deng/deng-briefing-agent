"""通用网页搜索：DuckDuckGo（ddgs），零密钥，覆盖新闻/博客等固定源扫不到的页面。"""

from __future__ import annotations

from typing import Any


def search_ddg(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """调用 ddgs 文本搜索。包没装或网络失败时抛异常，由收集器记录。"""
    from ddgs import DDGS

    raw = DDGS().text(query.strip(), max_results=max(1, min(limit, 10)))
    hits: list[dict[str, Any]] = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("href") or row.get("url") or "").strip()
        if not url:
            continue
        hits.append(
            {
                "title": str(row.get("title") or ""),
                "url": url,
                "snippet": str(row.get("body") or row.get("snippet") or ""),
                "sources": ["ddgs"],
                "kind": "web",
            }
        )
    return hits
