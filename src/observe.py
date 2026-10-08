"""把模型已经看过的工具结果收短。刚写回、还没读过的那一批保持全文。

完整正文在简报文件里。这里只改 messages 里的旧观察，避免下一轮把整页再送一遍。
"""

from __future__ import annotations

import json
import re
from typing import Any

# 一两句就够回忆「这页讲了什么」。更长的留给已经写进简报的正文。
_SENTENCE_LIMIT = 2
_CHAR_LIMIT = 400
_SENTENCE_RE = re.compile(r"[^。！？.!?]+[。！？.!?]?")


def two_sentences(text: str) -> str:
    """取前两句。没有句号的长段就按字数截断。"""
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    parts = [part.strip() for part in _SENTENCE_RE.findall(flat) if part.strip()]
    clipped = "".join(parts[:_SENTENCE_LIMIT]) if parts else flat
    if len(clipped) > _CHAR_LIMIT:
        return clipped[:_CHAR_LIMIT].rstrip() + "…"
    return clipped


def shorten_tool_content(content: str) -> str:
    """收短一条工具返回。写文件结果和错误原样留：路径和失败原因都很短，核对还要靠它们。"""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return two_sentences(content)
    if not isinstance(data, dict) or data.get("shortened"):
        return content
    if data.get("error") or ("ok" in data and data.get("path")):
        return content
    if isinstance(data.get("results"), list):
        data = _shorten_search(data)
    elif "text" in data:
        data = dict(data)
        data["text"] = two_sentences(str(data.get("text") or ""))
        data["shortened"] = True
    else:
        return content
    return json.dumps(data, ensure_ascii=False)


def shorten_seen_tools(messages: list[dict[str, Any]]) -> None:
    """最后一条 assistant 之后的 tool 是本轮刚拿到的，保持全文。更早的收短。"""
    last_assistant = -1
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            last_assistant = index
    for index, message in enumerate(messages):
        if message.get("role") != "tool" or index > last_assistant:
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content:
            continue
        message["content"] = shorten_tool_content(content)


def _shorten_search(data: dict[str, Any]) -> dict[str, Any]:
    """搜索结果只留标题、链接和两句摘要。url 必须留下，写完还要靠它核对。"""
    results = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        short: dict[str, Any] = {
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "snippet": two_sentences(str(item.get("snippet") or "")),
        }
        for key in ("sources", "kind", "arxiv_id", "repo"):
            if item.get(key):
                short[key] = item[key]
        results.append(short)
    shortened: dict[str, Any] = {"query": data.get("query") or "", "results": results, "shortened": True}
    if data.get("source_errors"):
        shortened["source_errors"] = data["source_errors"]
    if data.get("error"):
        shortened["error"] = data["error"]
    return shortened
