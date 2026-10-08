#!/usr/bin/env python3
"""把整个简报 Agent 包成一个 MCP 服务。

内部循环不变：仍是 run_agent 自己去搜索、抓页、写文件、核对。
这里不注册 web_search / fetch_url / write_file，避免外层模型把 Agent 拆开用。
stdio 的 stdout 只能走 MCP 协议，工具进度改打到 stderr。
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import main  # noqa: E402
from config import output_dir  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from receipt import LAST_RUN_NAME  # noqa: E402

mcp = FastMCP(
    "deng",
    instructions=(
        "这是简报 Agent 的外壳。run_briefing 和 resume_briefing 会在内部跑完整循环，"
        "包括搜索、抓页、写文件、链接核对和回执。这里没有 web_search、fetch_url、write_file。"
    ),
)


def _call_agent(prompt: str | None, *, session_id: str | None, resume: bool) -> dict:
    """调用和命令行相同的 execute。进度打印不能进 stdout，否则会冲掉 MCP 报文。"""
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        outcome = main.execute(prompt, session_id=session_id, resume=resume)
    progress = captured.getvalue().strip()
    if progress:
        print(progress, file=sys.stderr)
    if outcome.get("briefing"):
        path = output_dir() / Path(str(outcome["briefing"])).name
        if path.is_file():
            outcome = dict(outcome)
            outcome["briefing_markdown"] = path.read_text(encoding="utf-8")
    return outcome


@mcp.tool()
def run_briefing(prompt: str = "") -> dict:
    """跑一整次简报 Agent。prompt 留空则按北京时间做当天默认任务。

    返回回执结论：是否成功、文件路径、未核对条数、已报道条数、读过的页数。
    一页都没读到时 ok 为 false，这和命令行的空报规则相同。
    """
    text = prompt.strip() or None
    return _call_agent(text, session_id=None, resume=False)


@mcp.tool()
def resume_briefing(session_id: str, prompt: str = "") -> dict:
    """从已有 session 接着跑完整 Agent。prompt 留空时，已结束的会话会按原规则拒绝。"""
    if not session_id or not session_id.strip():
        return {"ok": False, "reason": "session_id is empty"}
    text = prompt.strip() or None
    return _call_agent(text, session_id=session_id.strip(), resume=True)


@mcp.resource("briefing://last-run", mime_type="text/markdown")
def last_run() -> str:
    """最近一次运行回执，和 output/last-run.md 是同一份。"""
    path = output_dir() / LAST_RUN_NAME
    if not path.is_file():
        return "还没有回执。"
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run(transport="stdio")
