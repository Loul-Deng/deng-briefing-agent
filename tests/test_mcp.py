"""MCP 外壳：对外只有整个 Agent，不把内部工具拆出去。不调用模型。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import main  # noqa: E402
import mcp_server  # noqa: E402


def test_mcp_tools_are_the_whole_agent() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == {"run_briefing", "resume_briefing"}
    assert "web_search" not in names
    assert "fetch_url" not in names
    assert "write_file" not in names


def test_run_briefing_calls_execute(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen: dict = {}

    def fake(prompt, *, session_id=None, resume=False):
        print("[tool] web_search ok=true query=llm")
        seen["prompt"] = prompt
        seen["session_id"] = session_id
        seen["resume"] = resume
        return {"ok": True, "reason": "", "briefing": "", "session_id": "sid"}

    monkeypatch.setattr(main, "execute", fake)
    outcome = mcp_server.run_briefing("")
    captured = capsys.readouterr()
    assert seen == {"prompt": None, "session_id": None, "resume": False}
    assert outcome["ok"] is True
    assert "[tool] web_search" not in captured.out
    assert "[tool] web_search" in captured.err


def test_resume_briefing_passes_follow_up(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake(prompt, *, session_id=None, resume=False):
        seen["prompt"] = prompt
        seen["session_id"] = session_id
        seen["resume"] = resume
        return {"ok": True, "session_id": session_id}

    monkeypatch.setattr(main, "execute", fake)
    mcp_server.resume_briefing("sid-1", "补充一篇")
    assert seen == {"prompt": "补充一篇", "session_id": "sid-1", "resume": True}


def test_last_run_resource_reads_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "output_dir", lambda: tmp_path)
    assert mcp_server.last_run() == "还没有回执。"
    (tmp_path / "last-run.md").write_text("# 运行回执\n\n- 结果：成功\n", encoding="utf-8")
    assert "结果：成功" in mcp_server.last_run()
