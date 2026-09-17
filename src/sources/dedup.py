"""把不同来源的链接收成同一把「身份证」，用来去重。

同一篇论文可能同时出现在 DuckDuckGo、arXiv API、Hugging Face Daily 里；
同一个仓库也可能是 github.com/owner/repo 和 trending 页两种 URL。
去重键优先：arxiv:年号.编号 → repo:owner/name → url:规范化路径。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# 匹配 2603.07670 或 2603.07670v1，覆盖 abs/pdf/html、"arXiv:..." 以及标题里的 [2502.12110]。
_ARXIV_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html)/|arxiv:\s*)(\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
_ARXIV_BRACKET_RE = re.compile(r"\[(\d{4}\.\d{4,5})(?:v\d+)?\]")
_GITHUB_RE = re.compile(r"github\.com/([^/]+)/([^/#?]+)", re.IGNORECASE)
# GitHub 站点自己的路径，不能当成仓库名。
_GITHUB_SKIP_OWNERS = {
    "topics",
    "trending",
    "orgs",
    "settings",
    "search",
    "features",
    "about",
    "login",
    "marketplace",
    "collections",
    "events",
    "sponsors",
}


def arxiv_id_from(text: str) -> str | None:
    """从 URL 或标题里抽出 arXiv id（去掉 vN 版本号）。找不到则返回 None。"""
    if not text:
        return None
    match = _ARXIV_RE.search(text) or _ARXIV_BRACKET_RE.search(text)
    return match.group(1) if match else None


def github_repo_from(url: str) -> str | None:
    """从 GitHub URL 抽出 owner/repo（小写、去掉 .git）。不是仓库页则返回 None。"""
    if not url:
        return None
    match = _GITHUB_RE.search(url)
    if not match:
        return None
    owner = match.group(1).lower()
    repo = match.group(2).lower().removesuffix(".git")
    if owner in _GITHUB_SKIP_OWNERS or repo in {"issues", "pulls", "actions"}:
        return None
    return f"{owner}/{repo}"


def canonical_url(url: str) -> str:
    """去掉协议差异、www、末尾斜杠，方便把同一页面当成同一条。"""
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = (parsed.path or "").rstrip("/").lower()
    if path.endswith(".pdf"):
        path = path[:-4]
    return f"{host}{path}"


def canonical_key(item: dict[str, Any]) -> str:
    """给一条搜索结果发身份证。相同 key 的条目在合并时会并成一条。"""
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    arxiv_id = item.get("arxiv_id") or arxiv_id_from(url) or arxiv_id_from(title)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    repo = item.get("repo") or github_repo_from(url)
    if repo:
        return f"repo:{repo}"
    return f"url:{canonical_url(url)}"


def merge_hits(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 canonical_key 合并：来源列表取并集，摘要保留更长的那份。"""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        if not url:
            continue
        item = dict(raw)
        item["url"] = url
        item["title"] = str(item.get("title") or "").strip()
        item["snippet"] = str(item.get("snippet") or "").strip()
        sources = item.get("sources") or item.get("source")
        if isinstance(sources, str):
            sources = [sources]
        if not isinstance(sources, list) or not sources:
            sources = ["unknown"]
        item["sources"] = list(dict.fromkeys(str(s) for s in sources))
        if not item.get("kind"):
            key_preview = canonical_key(item)
            if key_preview.startswith("arxiv:"):
                item["kind"] = "paper"
            elif key_preview.startswith("repo:"):
                item["kind"] = "repo"
            else:
                item["kind"] = "web"
        arxiv_id = item.get("arxiv_id") or arxiv_id_from(url) or arxiv_id_from(item["title"])
        if arxiv_id:
            item["arxiv_id"] = arxiv_id
            item["url"] = f"https://arxiv.org/abs/{arxiv_id}"
        repo = item.get("repo") or github_repo_from(item["url"])
        if repo:
            item["repo"] = repo

        key = canonical_key(item)
        if key not in merged:
            merged[key] = item
            order.append(key)
            continue
        old = merged[key]
        old["sources"] = list(dict.fromkeys([*old["sources"], *item["sources"]]))
        if len(item["snippet"]) > len(old.get("snippet") or ""):
            old["snippet"] = item["snippet"]
        if not old.get("title") and item.get("title"):
            old["title"] = item["title"]
        if item.get("arxiv_id"):
            old["arxiv_id"] = item["arxiv_id"]
        if item.get("repo"):
            old["repo"] = item["repo"]
    return [merged[key] for key in order]


def rank_hits(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """查询词命中标题/摘要的排前面；被多个源同时找到的再加分。"""
    tokens = [t.lower() for t in re.split(r"\s+", query.strip()) if len(t) >= 2]

    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        blob = f"{item.get('title') or ''} {item.get('snippet') or ''}".lower()
        hit = sum(1 for t in tokens if t in blob)
        source_n = len(item.get("sources") or [])
        kind_bonus = 2 if item.get("kind") in {"paper", "repo"} else 0
        return (hit, source_n, kind_bonus)

    return sorted(items, key=score, reverse=True)
