"""Agent 主循环：调模型 → 若有 tool_calls 则执行 → 把结果塞回 messages → 再调。

Loop 不知道业务（简报、论文），也不知道工具名叫什么。
退出：模型不再返回 tool_calls，或达到 max_turns。
"""

from __future__ import annotations

import json
import time
from typing import Any

from config import load_config
from llm import chat, create_client
from prompt import build_system_prompt
from registry import ToolRegistry, build_registry
from session import load_messages, new_session_id, save_messages
from trace import append_event


def _tool_ok(result: str) -> bool:
    """根据工具返回的 JSON 判断是否成功。解析不了就当成功（可能是纯文本）。"""
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return True
    return not (isinstance(data, dict) and data.get("error"))


def _assistant_dict(message: Any) -> dict[str, Any]:
    """把 SDK 的 message 对象收成可 JSON 序列化的 dict，方便写入 session。"""
    data: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        data["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in tool_calls
        ]
        if not data["content"]:
            data["content"] = None
    return data


def run_agent(
    user_text: str | None,
    *,
    session_id: str | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """跑完一次任务。resume=True 时从 sessions/<id>.jsonl 接着聊。"""
    cfg = load_config()
    model = (cfg.get("model") or {}).get("default") or "deepseek-chat"
    max_turns = int((cfg.get("agent") or {}).get("max_turns") or 12)
    registry: ToolRegistry = build_registry()
    tools = registry.list_schemas()
    client = create_client(cfg)

    if resume:
        if not session_id:
            raise ValueError("--resume needs a session id")
        messages = load_messages(session_id)
        if user_text:
            messages.append({"role": "user", "content": user_text})
        elif not messages:
            raise ValueError("session is empty")
        elif messages[-1]["role"] == "assistant" and not messages[-1].get("tool_calls"):
            raise ValueError("session already finished; pass a follow-up prompt after --resume")
    else:
        session_id = session_id or new_session_id()
        if not user_text:
            raise ValueError("a user prompt is required")
        messages = [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": user_text},
        ]

    save_messages(session_id, messages)
    append_event(session_id, {"type": "start", "model": model, "max_turns": max_turns})

    end_reason = "max_turns"
    final_text = ""
    turn = 0

    for turn in range(1, max_turns + 1):
        t0 = time.perf_counter()
        message = chat(client, model=model, messages=messages, tools=tools)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        assistant = _assistant_dict(message)
        messages.append(assistant)
        tool_calls = assistant.get("tool_calls") or []
        append_event(
            session_id,
            {
                "type": "llm",
                "turn": turn,
                "elapsed_ms": elapsed_ms,
                "has_tool_calls": bool(tool_calls),
                "tool_names": [tc["function"]["name"] for tc in tool_calls],
            },
        )
        save_messages(session_id, messages)

        if not tool_calls:
            final_text = assistant.get("content") or ""
            end_reason = "no_tool_calls"
            break

        for tc in tool_calls:
            name = tc["function"]["name"]
            arguments = tc["function"]["arguments"]
            print(f"[tool] {name} {arguments[:200]}")
            t1 = time.perf_counter()
            result = registry.call(name, arguments)
            tool_ms = int((time.perf_counter() - t1) * 1000)
            ok = _tool_ok(result)
            append_event(
                session_id,
                {
                    "type": "tool",
                    "turn": turn,
                    "name": name,
                    "elapsed_ms": tool_ms,
                    "ok": ok,
                    "result_chars": len(result),
                },
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": name,
                    "content": result,
                }
            )
            save_messages(session_id, messages)
    else:
        end_reason = "max_turns"

    append_event(session_id, {"type": "end", "reason": end_reason})
    save_messages(session_id, messages)
    return {
        "session_id": session_id,
        "end_reason": end_reason,
        "final_text": final_text,
        "turns": turn,
    }
