#!/usr/bin/env python3
"""CLI entry: python main.py "your briefing task" """

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import output_dir  # noqa: E402
from loop import run_agent  # noqa: E402
from prompt import beijing_today, default_user_prompt  # noqa: E402
from receipt import write_receipt  # noqa: E402


def _task_label(prompt: str | None, resume: bool) -> str:
    """无参数且不是续跑，才是每天的默认简报任务。"""
    if resume and not (prompt and prompt.strip()):
        return "resume"
    if not prompt or not prompt.strip():
        return "default"
    return "user"


def _display_path(path: str) -> str:
    """回执里写 output/文件名，不把本机绝对路径写进每天要看的那份说明。"""
    return f"output/{Path(path).name}"


def _record(day: str, **kwargs: object) -> None:
    """回执写失败不能把原来的运行错误盖掉。终端仍会看到 receipt 这一行。"""
    try:
        write_receipt(output_dir(), day=day, **kwargs)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        print(f"receipt: {exc}", file=sys.stderr)


def _outcome(**kwargs: object) -> dict:
    """CLI 和 MCP 看到的是同一份结论。缺的字段补空，避免两边各写一套。"""
    data = {
        "ok": False,
        "reason": "",
        "briefing": "",
        "unchecked": 0,
        "reported": 0,
        "pages_read": 0,
        "end_reason": "",
        "session_id": "",
        "final_text": "",
        "task": "",
        "show_log": False,
    }
    data.update(kwargs)
    return data


def execute(prompt: str | None, *, session_id: str | None = None, resume: bool = False) -> dict:
    """跑完 agent 并写回执。命令行和 MCP 都调用这里，空报规则不会分叉。"""
    day = beijing_today().isoformat()
    task = _task_label(prompt, resume)
    try:
        result = run_agent(prompt, session_id=session_id, resume=resume)
    except Exception as exc:  # noqa: BLE001
        _record(day, ok=False, reason=str(exc), session_id=session_id or "")
        return _outcome(reason=str(exc), task=task, session_id=session_id or "")
    return _settle(result, day=day, task=task)


def _settle(result: dict, *, day: str, task: str) -> dict:
    """有文件且至少读过一页才算成功。回执内容和退出结论用同一组数字。"""
    cite = result.get("cite") or {}
    session_id = str(result.get("session_id") or "")
    end_reason = str(result.get("end_reason") or "")
    final_text = str(result.get("final_text") or "")
    common = {
        "task": task,
        "session_id": session_id,
        "end_reason": end_reason,
        "final_text": final_text,
        "show_log": True,
        "pages_read": int(cite.get("pages_read") or 0),
    }
    # 没落盘就不算今天的简报完成。任务计划靠非 0 退出码看到失败。
    if cite.get("skipped") or not cite.get("path"):
        reason = str(cite.get("reason") or "no written file")
        _record(day, ok=False, reason=reason, end_reason=end_reason, session_id=session_id)
        return _outcome(reason=reason, **common)

    unchecked = cite.get("unchecked") or []
    reported = cite.get("reported") or []
    briefing = _display_path(str(cite["path"]))
    counts = {"briefing": briefing, "unchecked": len(unchecked), "reported": len(reported)}
    # 文件在，但工具里没有一次成功打开的页面：算空报，不当成功。
    if common["pages_read"] <= 0:
        reason = "空报：没有读到任何页面"
        _record(
            day,
            ok=False,
            reason=reason,
            briefing=briefing,
            unchecked=len(unchecked),
            reported=len(reported),
            end_reason=end_reason,
            session_id=session_id,
        )
        return _outcome(reason=reason, **common, **counts)

    _record(
        day,
        ok=True,
        briefing=briefing,
        unchecked=len(unchecked),
        reported=len(reported),
        end_reason=end_reason,
        session_id=session_id,
    )
    return _outcome(ok=True, **common, **counts)


def main() -> int:
    """解析命令行。真正的跑法和回执在 execute，和 MCP 外壳共用。"""
    parser = argparse.ArgumentParser(description="Frontier paper/OSS briefing agent")
    parser.add_argument("prompt", nargs="?", help="Briefing request. Omit to run today's default briefing.")
    parser.add_argument("--resume", metavar="SESSION_ID", help="Continue a session under sessions/")
    args = parser.parse_args()
    outcome = execute(args.prompt, session_id=args.resume, resume=bool(args.resume))
    if not outcome["ok"]:
        print(f"error: {outcome['reason']}", file=sys.stderr)
    if outcome["show_log"]:
        _print_run(outcome)
    return 0 if outcome["ok"] else 1


def _print_run(outcome: dict) -> None:
    """终端和回执写同一组数字：路径、未核对条数、已报道条数。"""
    print()
    print(f"task: {outcome['task']}")
    if outcome["task"] == "default":
        print(default_user_prompt())
    print(f"session: {outcome['session_id']}")
    print(f"end_reason: {outcome['end_reason']}")
    if outcome["briefing"]:
        print(f"briefing: {outcome['briefing']}")
        print(f"unchecked: {outcome['unchecked']}")
        print(f"reported: {outcome['reported']}")
    if outcome.get("final_text"):
        print()
        print(outcome["final_text"])
    print()
    print(f"session file: sessions/{outcome['session_id']}.jsonl")
    print(f"trace file:   traces/{outcome['session_id']}.jsonl")


if __name__ == "__main__":
    raise SystemExit(main())
