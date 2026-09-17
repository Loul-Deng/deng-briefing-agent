"""并行打一批信息源，再交给 dedup 合并。

设计要点：
- 模型仍然只看到一个工具 web_search，不会漏掉固定源。
- 单个源失败不影响其它源（错误写进 source_errors）。
- 合并后按查询词相关度排序，截断到 result_limit。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from config import load_config
from sources.arxiv import search_arxiv
from sources.ddg import search_ddg
from sources.dedup import merge_hits, rank_hits
from sources.github import fetch_github_trending, search_github_repos
from sources.hf_daily import fetch_hf_daily


def _enabled_sources(web: dict[str, Any]) -> dict[str, bool]:
    """读取 config.yaml 里 web.sources；缺省全部打开。"""
    configured = web.get("sources") or {}
    defaults = {
        "ddgs": True,
        "arxiv": True,
        "github_search": True,
        "github_trending": True,
        "hf_daily": True,
    }
    if not isinstance(configured, dict):
        return defaults
    out = dict(defaults)
    for name, flag in configured.items():
        out[str(name)] = bool(flag)
    return out


def _run_source(name: str, fn: Callable[[], list[dict[str, Any]]]) -> tuple[str, list[dict[str, Any]] | None, str | None]:
    """跑一个源：成功返回列表，失败返回错误字符串。"""
    try:
        return name, fn(), None
    except Exception as exc:  # noqa: BLE001 — 单源失败不能拖垮整次搜索
        return name, None, f"{type(exc).__name__}: {exc}"


def collect_hits(query: str, limit: int) -> dict[str, Any]:
    """同时请求 DDG + 固定源，去重后返回给 web_search。"""
    web = load_config().get("web") or {}
    enabled = _enabled_sources(web)
    per_source = max(1, min(int(limit), 10))
    result_limit = int(web.get("result_limit") or 15)
    timeout = float(web.get("source_timeout_sec") or 15)
    trending_since = str(web.get("github_trending_since") or "weekly")
    trending_lang = str(web.get("github_trending_language") or "")

    jobs: dict[str, Callable[[], list[dict[str, Any]]]] = {}
    if enabled.get("ddgs"):
        jobs["ddgs"] = lambda: search_ddg(query, per_source)
    if enabled.get("arxiv"):
        jobs["arxiv"] = lambda: search_arxiv(query, per_source, timeout=timeout)
    if enabled.get("github_search"):
        jobs["github_search"] = lambda: search_github_repos(query, per_source, timeout=timeout)
    if enabled.get("github_trending"):
        jobs["github_trending"] = lambda: fetch_github_trending(
            since=trending_since,
            language=trending_lang,
            limit=per_source,
            timeout=timeout,
        )
    if enabled.get("hf_daily"):
        jobs["hf_daily"] = lambda: fetch_hf_daily(per_source, timeout=timeout)

    raw_items: list[dict[str, Any]] = []
    source_errors: dict[str, str] = {}
    source_counts: dict[str, int] = {}

    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(_run_source, name, fn) for name, fn in jobs.items()]
            for fut in as_completed(futures):
                name, hits, err = fut.result()
                if err:
                    source_errors[name] = err
                    source_counts[name] = 0
                    continue
                assert hits is not None
                source_counts[name] = len(hits)
                raw_items.extend(hits)

    merged = merge_hits(raw_items)
    ranked = rank_hits(merged, query)[: max(1, result_limit)]
    return {
        "query": query,
        "results": ranked,
        "source_counts": source_counts,
        "source_errors": source_errors,
        "deduped_from": len(raw_items),
        "deduped_to": len(merged),
    }
