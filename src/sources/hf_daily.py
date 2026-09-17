"""固定信息源：Hugging Face Daily Papers（社区投票的当日论文，无密钥）。"""

from __future__ import annotations

from typing import Any

import httpx

from sources.dedup import arxiv_id_from

_HF_DAILY = "https://huggingface.co/api/daily_papers"


def fetch_hf_daily(limit: int = 8, timeout: float = 15.0) -> list[dict[str, Any]]:
    """拉取 HF Daily Papers。条目里通常带 arXiv id，去重时能和 arXiv API 撞上。"""
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "DENG-briefing-agent/0.1", "Accept": "application/json"},
    ) as client:
        response = client.get(_HF_DAILY)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        return []
    hits: list[dict[str, Any]] = []
    for row in payload[: max(1, min(limit, 20))]:
        paper = row.get("paper") if isinstance(row, dict) else None
        if not isinstance(paper, dict):
            paper = row if isinstance(row, dict) else {}
        paper_id = str(paper.get("id") or row.get("id") or "")
        title = str(paper.get("title") or row.get("title") or "").strip()
        summary = str(paper.get("summary") or paper.get("abstract") or row.get("summary") or "").strip()
        arxiv_id = arxiv_id_from(paper_id) or arxiv_id_from(str(paper.get("arxiv_id") or ""))
        if arxiv_id:
            url = f"https://arxiv.org/abs/{arxiv_id}"
        elif paper_id:
            url = f"https://huggingface.co/papers/{paper_id}"
        else:
            continue
        hits.append(
            {
                "title": title or paper_id,
                "url": url,
                "snippet": summary[:500],
                "sources": ["hf_daily"],
                "kind": "paper",
                "arxiv_id": arxiv_id,
            }
        )
    return hits
