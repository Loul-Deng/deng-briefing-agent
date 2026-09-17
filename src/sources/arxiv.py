"""固定信息源：arXiv 官方 Atom API。不需要密钥。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
import httpx

from sources.dedup import arxiv_id_from

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_API = "https://export.arxiv.org/api/query"


def search_arxiv(query: str, limit: int = 5, timeout: float = 15.0) -> list[dict[str, Any]]:
    """按关键词检索 arXiv，按提交时间倒序。失败时抛出异常，由上层记入 source_errors。"""
    text = query.strip() or "cs.AI"
    params = {
        "search_query": f"all:{text}",
        "start": 0,
        "max_results": max(1, min(limit, 15)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "DENG-briefing-agent/0.1"}) as client:
        response = client.get(_ARXIV_API, params=params)
        response.raise_for_status()
    return _parse_atom(response.text)


def _parse_atom(xml_text: str) -> list[dict[str, Any]]:
    """把 arXiv 返回的 Atom XML 转成统一的 hit 字典列表。"""
    root = ET.fromstring(xml_text)
    hits: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM}entry"):
        raw_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        summary = " ".join((entry.findtext(f"{_ATOM}summary") or "").split())
        arxiv_id = arxiv_id_from(raw_id)
        if not arxiv_id:
            continue
        hits.append(
            {
                "title": title,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "snippet": summary[:500],
                "sources": ["arxiv"],
                "kind": "paper",
                "arxiv_id": arxiv_id,
            }
        )
    return hits
