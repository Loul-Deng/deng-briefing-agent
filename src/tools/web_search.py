"""web_search 工具：对外仍是一个函数，对内并行打 DDG + 固定源并去重。

不要把「换搜索引擎」做成模型可调用的密钥工具；开关在 config.yaml 的 web.sources。
"""

from __future__ import annotations

import json

from registry import ToolRegistry
from sources.collect import collect_hits


def web_search(query: str, limit: int = 5) -> str:
    """搜索论文/仓库/网页。limit 是「每个源」的条数上限，合并去重后再截断。"""
    if not query or not str(query).strip():
        return json.dumps({"error": "query is empty"}, ensure_ascii=False)
    try:
        n = int(limit) if limit is not None else 5
    except (TypeError, ValueError):
        n = 5
    n = max(1, min(n, 10))
    try:
        payload = collect_hits(str(query).strip(), n)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"search failed: {exc}", "query": query}, ensure_ascii=False)
    if not payload.get("results") and payload.get("source_errors"):
        payload["error"] = "all sources failed"
    return json.dumps(payload, ensure_ascii=False)


def register(registry: ToolRegistry) -> None:
    """把 web_search 登记进注册表，供 Loop 按名字调用。"""
    registry.register(
        name="web_search",
        description=(
            "Search papers and open-source projects. Internally queries DuckDuckGo, "
            "arXiv, GitHub search, GitHub Trending, and Hugging Face Daily Papers, "
            "then deduplicates by arXiv id / GitHub repo / URL. "
            "Returns title, url, snippet, sources, and kind. Then fetch_url the best links."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, preferably in English for papers.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per source (1-10). Merged list may be longer.",
                },
            },
            "required": ["query"],
        },
        handler=web_search,
    )
