"""固定信息源：GitHub 仓库搜索 + Trending。搜索走官方 API；Trending 解析公开 HTML。"""

from __future__ import annotations

import re
from typing import Any
import httpx

from sources.dedup import github_repo_from

_UA = {"User-Agent": "DENG-briefing-agent/0.1", "Accept": "application/vnd.github+json"}
_TRENDING_HREF = re.compile(
    r'<h2[^>]*>\s*<a[^>]+href="/(?P<owner>[^/]+)/(?P<repo>[^"/]+)"',
    re.IGNORECASE,
)


def search_github_repos(query: str, limit: int = 5, timeout: float = 15.0) -> list[dict[str, Any]]:
    """用 GitHub Search API 找最近更新的仓库。无 Token 时可能触发速率限制，由上层吞掉错误。"""
    q = (query.strip() or "LLM agent") + " in:name,description"
    params = {
        "q": q,
        "sort": "updated",
        "order": "desc",
        "per_page": max(1, min(limit, 10)),
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=_UA) as client:
        response = client.get("https://api.github.com/search/repositories", params=params)
        response.raise_for_status()
        payload = response.json()
    hits: list[dict[str, Any]] = []
    for repo in payload.get("items") or []:
        full = str(repo.get("full_name") or "")
        html_url = str(repo.get("html_url") or "")
        if not html_url:
            continue
        desc = str(repo.get("description") or "")
        hits.append(
            {
                "title": full or repo.get("name") or html_url,
                "url": html_url,
                "snippet": desc,
                "sources": ["github_search"],
                "kind": "repo",
                "repo": full.lower() if full else github_repo_from(html_url),
            }
        )
    return hits


def fetch_github_trending(
    *,
    since: str = "weekly",
    language: str = "",
    limit: int = 8,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """抓取 GitHub Trending 页面上的仓库列表（不依赖 Token）。"""
    since = since if since in {"daily", "weekly", "monthly"} else "weekly"
    path = f"https://github.com/trending/{language}" if language else "https://github.com/trending"
    url = f"{path}?since={since}"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DENG-briefing-agent/0.1; research briefing)",
        "Accept": "text/html",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        html = response.text
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _TRENDING_HREF.finditer(html):
        owner = match.group("owner")
        repo = match.group("repo")
        full = f"{owner}/{repo}"
        if full.lower() in seen:
            continue
        seen.add(full.lower())
        hits.append(
            {
                "title": full,
                "url": f"https://github.com/{full}",
                "snippet": f"GitHub trending ({since})" + (f" language={language}" if language else ""),
                "sources": ["github_trending"],
                "kind": "repo",
                "repo": full.lower(),
            }
        )
        if len(hits) >= limit:
            break
    return hits
