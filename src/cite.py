"""写盘之后核对简报链接。这是程序必做的检查，不是模型可以跳过的工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 末尾这一节是程序追加的，不算模型写的正文。重复核对时先切掉再抽链接。
UNCHECKED_HEADING = "## 未核对链接"
_URL_RE = re.compile(r"https?://[^\s)>\]]+")


def _normalize_url(url: str) -> str:
    """去掉末尾标点和斜杠，让正文链接和工具返回能对上。"""
    text = url.strip().rstrip(".,;:，。；、")
    if text.endswith("/"):
        text = text[:-1]
    return text


def _harvest(data: Any, seen: set[str]) -> None:
    """从一条工具 JSON 里收集 url，以及 results 列表里每一项的 url。"""
    if isinstance(data, dict):
        url = data.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            seen.add(_normalize_url(url))
        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                _harvest(item, seen)
    elif isinstance(data, list):
        for item in data:
            _harvest(item, seen)


def pages_read(messages: list[dict[str, Any]]) -> int:
    """数真正打开过的页面。搜索摘要和写文件不算读过。

    认 JSON 形状：有 url、有非空 text、没有 error。不认工具名。
    收短后的正文仍算读过，因为全文在收短前已经进过对话。
    """
    count = 0
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            data = json.loads(message.get("content") or "")
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("error"):
            continue
        url = data.get("url")
        text = data.get("text")
        if (
            isinstance(url, str)
            and url.startswith(("http://", "https://"))
            and isinstance(text, str)
            and text.strip()
        ):
            count += 1
    return count


def collect_seen_urls(messages: list[dict[str, Any]]) -> set[str]:
    """本轮所有 tool 消息里出现过的 URL。认 JSON 形状，不认工具名。"""
    seen: set[str] = set()
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            data = json.loads(message.get("content") or "")
        except json.JSONDecodeError:
            continue
        _harvest(data, seen)
    return seen


def extract_md_urls(text: str) -> list[str]:
    """按出现顺序抽出正文里的 http(s) 链接，并去重。"""
    found: list[str] = []
    seen: set[str] = set()
    for raw in _URL_RE.findall(text):
        url = _normalize_url(raw)
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found


def _body(text: str) -> str:
    """切掉程序上次追加的「未核对」小节，避免把标注本身再当成引用。"""
    marker = f"\n{UNCHECKED_HEADING}"
    if text.startswith(UNCHECKED_HEADING):
        return ""
    return text.split(marker)[0].rstrip()


def check_briefing(path: str | Path, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """差集 = 正文有、工具返回里从未出现的链接。只标注，不打回模型重写。

    全部能对上时不改正文；若上次标过、这次又能对上，则删掉旧标注。
    """
    target = Path(path)
    if not target.is_file():
        return {
            "skipped": True,
            "reason": "file missing",
            "unchecked": [],
            "path": str(target),
        }

    original = target.read_text(encoding="utf-8")
    body = _body(original)
    seen = collect_seen_urls(messages)
    unchecked = [url for url in extract_md_urls(body) if url not in seen]

    if unchecked:
        lines = "\n".join(f"- {url}" for url in unchecked)
        appendix = (
            f"\n\n{UNCHECKED_HEADING}\n\n"
            "以下链接未出现在本轮工具返回中，结论请人工复核：\n\n"
            f"{lines}\n"
        )
        target.write_text(body + appendix, encoding="utf-8")
    elif f"\n{UNCHECKED_HEADING}" in original or original.startswith(UNCHECKED_HEADING):
        target.write_text(body + "\n", encoding="utf-8")

    return {"skipped": False, "unchecked": unchecked, "path": str(target)}
