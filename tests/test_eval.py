"""十道评测：真实 DeepSeek。没有密钥则整文件跳过，不假装通过。

空搜索那一题仍把 web_search / fetch_url 的返回钉死，否则无法稳定复现「没有读到任何链接」。
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

load_dotenv(ROOT / ".env")
if not os.getenv("DEEPSEEK_API_KEY", "").strip():
    pytest.skip("DEEPSEEK_API_KEY missing", allow_module_level=True)

from config import load_config  # noqa: E402
from loop import run_agent  # noqa: E402
from registry import ToolRegistry  # noqa: E402
from session import save_messages  # noqa: E402
from tools.write_file import write_file  # noqa: E402

pytestmark = pytest.mark.live

_FAKE = "https://example.com/eval-unchecked"
_OLD = "https://arxiv.org/abs/2609.08149"


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, agent: dict | None = None) -> Path:
    """会话、trace、简报进临时目录，并收紧轮数和时间。不替换 chat。"""
    out = tmp_path / "output"
    out.mkdir()
    cfg = copy.deepcopy(load_config())
    agent_cfg = dict(cfg.get("agent") or {})
    agent_cfg["max_turns"] = 4
    agent_cfg["max_minutes"] = 3
    if agent:
        agent_cfg.update(agent)
    cfg["agent"] = agent_cfg
    monkeypatch.setattr("loop.load_config", lambda: cfg)
    monkeypatch.setattr("loop.output_dir", lambda _cfg=None: out)
    monkeypatch.setattr("tools.write_file.output_dir", lambda _cfg=None: out)
    monkeypatch.setattr("session.SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr("trace.TRACES_DIR", tmp_path / "traces")
    return out


def _events(tmp_path: Path, session_id: str) -> list[dict]:
    """读这次运行的 trace。"""
    path = tmp_path / "traces" / f"{session_id}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _llm_count(events: list[dict]) -> int:
    return sum(1 for event in events if event.get("type") == "llm")


def _briefings(out: Path) -> list[Path]:
    return [path for path in out.glob("*.md") if path.name.lower() != "index.md"]


def test_live_first_turn_searches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    result = run_agent("请先调用 web_search 搜索 LLM agent memory，然后再决定要不要写简报。")
    names = " ".join(json.dumps(event, ensure_ascii=False) for event in _events(tmp_path, result["session_id"]))
    assert "web_search" in names


def test_live_briefing_urls_were_seen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _isolate(monkeypatch, tmp_path)
    result = run_agent(
        "写一份很短的简报，只保留 1 篇论文。"
        "正文里的每个链接都必须来自本轮 web_search 或 fetch_url 的返回。"
        "没读到就写「未读到」，不要编造链接。"
    )
    assert result["cite"].get("skipped") is not True
    assert result["cite"]["unchecked"] == []
    assert _briefings(out)


def test_live_forced_unseen_url_is_marked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _isolate(monkeypatch, tmp_path)
    result = run_agent(
        "写一份简报文件。"
        f"正文必须原样包含这个链接：{_FAKE} 。"
        "不要调用 fetch_url 去打开它。"
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in _briefings(out))
    assert _FAKE in result["cite"]["unchecked"]
    assert "未核对链接" in text
    assert _FAKE in text


def test_live_empty_search_flags_invented_urls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _isolate(monkeypatch, tmp_path)
    original = ToolRegistry.call

    def call(self: ToolRegistry, name: str, arguments: str | dict | None) -> str:
        # 真实搜索无法稳定给出空列表。fetch 也不返回 url，避免模型靠抓页把链接变成「见过」。
        if name == "web_search":
            return json.dumps({"results": [], "query": "empty"}, ensure_ascii=False)
        if name == "fetch_url":
            return json.dumps({"error": "fetch disabled in this test"}, ensure_ascii=False)
        return original(self, name, arguments)

    monkeypatch.setattr(ToolRegistry, "call", call)
    result = run_agent("请搜索并写一份简报。如果没有读到材料，写「未读到」，不要编造链接。")
    from cite import extract_md_urls
    from history import article_body

    unchecked = set(result["cite"].get("unchecked") or [])
    for path in _briefings(out):
        for url in extract_md_urls(article_body(path.read_text(encoding="utf-8"))):
            assert url in unchecked


def test_live_history_url_is_labeled_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _isolate(monkeypatch, tmp_path)
    (out / "old.md").write_text(f"昨天已报道 {_OLD}\n", encoding="utf-8")
    result = run_agent(
        "写一份新简报文件。"
        f"正文必须原样包含这个链接：{_OLD} 。"
        "写完即可，不必再搜索。"
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in _briefings(out) if path.name != "old.md")
    assert _OLD in (result["cite"].get("reported") or [])
    assert "以下链接已在更早的简报中出现" in text
    assert _OLD in text.split("## 已报道", 1)[1]


def test_live_second_write_does_not_overwrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _isolate(monkeypatch, tmp_path, agent={"max_turns": 2})
    run_agent("只回复一个字：好。不要调用任何工具。")
    write_file("briefing.md", "first")
    write_file("briefing.md", "second")
    assert (out / "briefing.md").read_text(encoding="utf-8") == "first"
    assert (out / "briefing-2.md").read_text(encoding="utf-8") == "second"


def test_live_rejects_index_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path, agent={"max_turns": 2})
    run_agent("只回复一个字：好。不要调用任何工具。")
    with pytest.raises(ValueError, match="index.md"):
        write_file("index.md", "# 不许写")


def test_live_max_turns_adds_wrap_up_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path, agent={"max_turns": 1, "max_minutes": 3})
    result = run_agent(
        "请先调用 web_search 搜索 LLM agent memory。"
        "这一轮只许调用工具，不要直接给出最终文字答复，也不要调用 write_file。"
    )
    events = _events(tmp_path, result["session_id"])
    assert result["end_reason"] == "wrap_up"
    assert _llm_count(events) >= 2


def test_live_zero_minutes_is_one_wrap_up_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path, agent={"max_minutes": 0, "max_turns": 4})
    result = run_agent("写一份简报。")
    events = _events(tmp_path, result["session_id"])
    assert result["end_reason"] == "budget"
    assert _llm_count(events) == 1


def test_live_resume_runs_pending_tool_before_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _isolate(monkeypatch, tmp_path, agent={"max_turns": 2})
    arguments = json.dumps({"path": "from-resume.md", "content": "续写完成\n"}, ensure_ascii=False)
    save_messages(
        "sid-pending",
        [
            {"role": "system", "content": "你是简报助手。"},
            {"role": "user", "content": "写文件"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "p1",
                        "type": "function",
                        "function": {"name": "write_file", "arguments": arguments},
                    }
                ],
            },
        ],
    )
    result = run_agent("用一句话确认文件已经写好。", session_id="sid-pending", resume=True)
    events = _events(tmp_path, result["session_id"])
    tool_at = next(index for index, event in enumerate(events) if event.get("type") == "tool")
    llm_at = next(index for index, event in enumerate(events) if event.get("type") == "llm")
    assert tool_at < llm_at
    assert (out / "from-resume.md").is_file()

    save_messages(
        "sid-done",
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "写"},
            {"role": "assistant", "content": "已经写完"},
        ],
    )
    with pytest.raises(ValueError, match="already finished"):
        run_agent(None, session_id="sid-done", resume=True)
