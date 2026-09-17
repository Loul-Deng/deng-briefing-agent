"""会话持久化：一个对话一个 JSONL，一行一条 message，支持 --resume。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import ROOT

SESSIONS_DIR = ROOT / "sessions"


def new_session_id() -> str:
    """用本地时间生成会话 id，例如 20260917_101500。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def session_path(session_id: str) -> Path:
    """会话文件路径；必要时创建 sessions/ 目录。"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR / f"{session_id}.jsonl"


def save_messages(session_id: str, messages: list[dict[str, Any]]) -> Path:
    """整表覆盖写入。每轮结束后都存，崩溃后也能 resume。"""
    path = session_path(session_id)
    with path.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return path


def load_messages(session_id: str) -> list[dict[str, Any]]:
    """读回历史 messages。文件不存在则报错，让 CLI 给出明确提示。"""
    path = session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"session not found: {path}")
    messages: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages
