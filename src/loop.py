"""Agent 主循环：调模型 → 若有 tool_calls 则执行 → 把结果塞回 messages → 再调。

Loop 不知道业务（简报、论文），也不知道工具名叫什么。
退出：模型不再返回 tool_calls，或达到 max_turns，或时间/token 预算用尽。
轮数或预算用尽仍未写盘时，再追问一轮，要求立刻写文件。
"""

from __future__ import annotations

import json
import time
from typing import Any

from cite import check_briefing, pages_read
from config import load_config, output_dir
from history import mark_reported, reported_urls, update_index
from observe import shorten_seen_tools
from llm import chat, create_client
from prompt import WRAP_UP_PROMPT, build_system_prompt, default_user_prompt
from registry import ToolRegistry, build_registry
from session import load_messages, new_session_id, save_messages
from trace import append_event

_PRINT_KEYS = ("query", "url", "path")


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


def _tool_fields(arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    """从参数里取出 query / url / path。解析失败就当没有这些字段，不按工具名分支。"""
    if isinstance(arguments, dict):
        data: Any = arguments
    else:
        try:
            data = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, dict):
        return {}
    return {key: data[key] for key in _PRINT_KEYS if data.get(key) not in (None, "")}


def _short(value: Any, limit: int = 200) -> str:
    """打印和 trace 只留前 200 字，避免一条查询把终端刷满。"""
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _print_tool(name: str, ok: bool, fields: dict[str, Any]) -> None:
    """必须在 registry.call 之后打印：这时才有 ok。"""
    bits = [f"[tool] {name} ok={str(ok).lower()}"]
    for key in _PRINT_KEYS:
        if fields.get(key):
            bits.append(f"{key}={_short(fields[key])}")
    print(" ".join(bits))


def _tool_payload(message: dict[str, Any]) -> dict[str, Any] | None:
    """把一条 tool 消息解析成 dict。不是 JSON 或不是对象就跳过。"""
    if message.get("role") != "tool":
        return None
    try:
        data = json.loads(message.get("content") or "")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _is_written_file(payload: dict[str, Any]) -> bool:
    """成功写盘的形状：ok 为真，且带 path 或 relative。不看工具名叫什么。"""
    return payload.get("ok") is True and bool(payload.get("path") or payload.get("relative"))


def _last_written_path(messages: list[dict[str, Any]]) -> str | None:
    """最后一次成功写盘的路径。优先绝对 path，没有再退回 relative。"""
    found: str | None = None
    for message in messages:
        payload = _tool_payload(message)
        if payload and _is_written_file(payload):
            found = str(payload.get("path") or payload.get("relative"))
    return found


def _has_written_file(messages: list[dict[str, Any]]) -> bool:
    """本轮对话里是否已经有一份落盘的简报。"""
    return _last_written_path(messages) is not None


def _pending_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """找出还没有对应 tool 消息的 tool_calls。

    崩溃若发生在 call 之前，session 里会留下「assistant 已声明调用、结果还没写回」。
    续跑必须先补执行，否则下一次 chat 会因协议不完整被接口拒绝。
    """
    if not messages:
        return []
    answered: set[str] = set()
    index = len(messages) - 1
    while index >= 0 and messages[index].get("role") == "tool":
        tool_call_id = messages[index].get("tool_call_id")
        if tool_call_id:
            answered.add(str(tool_call_id))
        index -= 1
    if index < 0 or messages[index].get("role") != "assistant":
        return []
    pending: list[dict[str, Any]] = []
    for call in messages[index].get("tool_calls") or []:
        if str(call.get("id")) not in answered:
            pending.append(call)
    return pending


def _append_wrap_up(messages: list[dict[str, Any]]) -> None:
    """追加收尾指令。紧挨着的上一条已经是同一句时不重复塞。"""
    if messages and messages[-1].get("role") == "user" and messages[-1].get("content") == WRAP_UP_PROMPT:
        return
    messages.append({"role": "user", "content": WRAP_UP_PROMPT})


def _execute_tool_batch(
    session_id: str,
    registry: ToolRegistry,
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    turn: int,
) -> None:
    """执行本轮全部 tool_calls，再进入下一次 chat。打印和 trace 都在 call 之后。"""
    for call in tool_calls:
        name = call["function"]["name"]
        arguments = call["function"]["arguments"]
        fields = _tool_fields(arguments)
        started = time.perf_counter()
        result = registry.call(name, arguments)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        ok = _tool_ok(result)
        _print_tool(name, ok, fields)
        event: dict[str, Any] = {
            "type": "tool",
            "turn": turn,
            "name": name,
            "elapsed_ms": elapsed_ms,
            "ok": ok,
            "result_chars": len(result),
        }
        for key in _PRINT_KEYS:
            if fields.get(key):
                event[key] = _short(fields[key])
        append_event(session_id, event)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name,
                "content": result,
            }
        )
        save_messages(session_id, messages)


def _budget_reason(
    started: float,
    tokens: int,
    max_minutes: float,
    max_tokens: int,
) -> str | None:
    """墙钟或累计 token 超限时返回原因。0 表示一开始就超，用来立刻收尾。"""
    elapsed_minutes = (time.perf_counter() - started) / 60
    if elapsed_minutes >= max_minutes:
        return "time"
    if tokens >= max_tokens:
        return "tokens"
    return None


def _run_model_turn(
    *,
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    registry: ToolRegistry,
    session_id: str,
    turn: int,
    usage_total: list[int],
) -> str | None:
    """问模型一轮。没有 tool_calls 就返回正文；有则全部执行后返回 None。usage_total 就地累加。"""
    # 上一轮已经看过的工具结果收短。刚追加、还排在最后一条 assistant 后面的保持全文。
    shorten_seen_tools(messages)
    started = time.perf_counter()
    message, usage = chat(client, model=model, messages=messages, tools=tools)
    usage_total[0] += int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
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
            "tool_names": [call["function"]["name"] for call in tool_calls],
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    )
    save_messages(session_id, messages)
    if not tool_calls:
        return assistant.get("content") or ""
    _execute_tool_batch(session_id, registry, messages, tool_calls, turn)
    return None


def _record_cite(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    url_limit: int,
) -> dict[str, Any]:
    """核对链接，再把历史里出现过的 URL 标成已报道，并刷新索引。"""
    path = _last_written_path(messages)
    if not path:
        info: dict[str, Any] = {"skipped": True, "reason": "no written file", "unchecked": [], "reported": []}
    else:
        info = check_briefing(path, messages)
        known = reported_urls(output_dir(), url_limit, exclude=path)
        info["reported"] = mark_reported(path, known)
    # 写出文件但一页都没读到，也要把这个数交给回执。搜索摘要不算读过。
    info["pages_read"] = pages_read(messages)
    update_index(output_dir())
    append_event(
        session_id,
        {
            "type": "cite",
            "skipped": bool(info.get("skipped")),
            "reason": info.get("reason"),
            "path": info.get("path") or path,
            "unchecked": info.get("unchecked") or [],
            "reported": info.get("reported") or [],
            "pages_read": info.get("pages_read") or 0,
        },
    )
    return info


def run_agent(
    user_text: str | None,
    *,
    session_id: str | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """跑完一次任务。不传 user_text 时用当天默认简报；resume=True 时从 sessions/<id>.jsonl 接着聊。"""
    cfg = load_config()
    model = (cfg.get("model") or {}).get("default") or "deepseek-chat"
    agent_cfg = cfg.get("agent") or {}
    max_turns = int(agent_cfg.get("max_turns") or 12)
    # 用 is not None：0 是合法值，表示一开始就超预算。
    max_minutes = float(8 if agent_cfg.get("max_minutes") is None else agent_cfg.get("max_minutes"))
    max_tokens = int(150000 if agent_cfg.get("max_tokens") is None else agent_cfg.get("max_tokens"))
    url_limit = int(((cfg.get("history") or {}).get("url_limit")) or 40)
    registry: ToolRegistry = build_registry()
    tools = registry.list_schemas()
    client = create_client(cfg)
    known = reported_urls(output_dir(), url_limit)

    pending: list[dict[str, Any]] = []
    if resume:
        if not session_id:
            raise ValueError("--resume needs a session id")
        messages = load_messages(session_id)
        if not messages:
            raise ValueError("session is empty")
        # 在追加新 user 之前记下待补工具。追加后再看，新问题会挡住未完成的 tool_calls。
        pending = _pending_tool_calls(messages)
        follow_up = bool(user_text and str(user_text).strip())
        if (
            not pending
            and not follow_up
            and messages[-1]["role"] == "assistant"
            and not messages[-1].get("tool_calls")
        ):
            raise ValueError("session already finished; pass a follow-up prompt after --resume")
    else:
        session_id = session_id or new_session_id()
        if not user_text or not str(user_text).strip():
            user_text = default_user_prompt()
        messages = [
            {"role": "system", "content": build_system_prompt(session_id, known)},
            {"role": "user", "content": user_text},
        ]

    save_messages(session_id, messages)
    append_event(session_id, {"type": "start", "model": model, "max_turns": max_turns})
    if resume and pending:
        _execute_tool_batch(session_id, registry, messages, pending, turn=0)
    if resume and user_text and str(user_text).strip():
        messages.append({"role": "user", "content": user_text})
        save_messages(session_id, messages)

    started = time.perf_counter()
    usage_total = [0]
    end_reason = "max_turns"
    budget_hit: str | None = None
    final_text = ""
    turn = 0

    for turn in range(1, max_turns + 1):
        budget_hit = _budget_reason(started, usage_total[0], max_minutes, max_tokens)
        if budget_hit:
            end_reason = "budget"
            break
        # 已经干过一轮、仍没写盘，才在最后一两轮改口要求写文件。
        # 第一轮不塞：max_turns=1 时否则用户任务会被收尾指令盖住，来不及调用工具。
        if turn > 1 and turn >= max_turns - 1 and not _has_written_file(messages):
            _append_wrap_up(messages)
            save_messages(session_id, messages)
        text = _run_model_turn(
            client=client,
            model=model,
            messages=messages,
            tools=tools,
            registry=registry,
            session_id=session_id,
            turn=turn,
            usage_total=usage_total,
        )
        if text is not None:
            final_text = text
            end_reason = "no_tool_calls"
            break
    else:
        end_reason = "max_turns"

    if end_reason in {"max_turns", "budget"} and not _has_written_file(messages):
        # 轮数或预算用尽且文件还没有：再问一次。工具仍开着，只追加收尾指令。
        _append_wrap_up(messages)
        save_messages(session_id, messages)
        turn = turn + 1
        text = _run_model_turn(
            client=client,
            model=model,
            messages=messages,
            tools=tools,
            registry=registry,
            session_id=session_id,
            turn=turn,
            usage_total=usage_total,
        )
        if text is not None:
            final_text = text
        if end_reason != "budget":
            end_reason = "wrap_up"

    cite = _record_cite(session_id, messages, url_limit=url_limit)
    append_event(
        session_id,
        {"type": "end", "reason": end_reason, "budget": budget_hit, "total_tokens": usage_total[0]},
    )
    save_messages(session_id, messages)
    return {
        "session_id": session_id,
        "end_reason": end_reason,
        "final_text": final_text,
        "turns": turn,
        "cite": cite,
    }
