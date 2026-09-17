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

from loop import run_agent  # noqa: E402


def main() -> int:
    """解析命令行、跑 agent、把 session/trace 路径打印出来。"""
    parser = argparse.ArgumentParser(description="Frontier paper/OSS briefing agent (P0)")
    parser.add_argument("prompt", nargs="?", help="Briefing request in natural language")
    parser.add_argument("--resume", metavar="SESSION_ID", help="Continue a session under sessions/")
    args = parser.parse_args()

    try:
        result = run_agent(args.prompt, session_id=args.resume, resume=bool(args.resume))
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"session: {result['session_id']}")
    print(f"end_reason: {result['end_reason']}")
    if result.get("final_text"):
        print()
        print(result["final_text"])
    print()
    print(f"session file: sessions/{result['session_id']}.jsonl")
    print(f"trace file:   traces/{result['session_id']}.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
