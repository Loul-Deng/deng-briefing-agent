"""追踪日志：每次 LLM / 工具 / 结束追加一行 JSON。面试时对着这条讲「搜了什么、读了哪页」。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import ROOT

TRACES_DIR = ROOT / "traces"


def trace_path(session_id: str) -> Path:
    """追踪文件路径，与 session id 一一对应。"""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    return TRACES_DIR / f"{session_id}.jsonl"


def append_event(session_id: str, event: dict[str, Any]) -> None:
    """追加一条事件。自动补 UTC 时间戳，不改调用方传入的字段。"""
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    path = trace_path(session_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
