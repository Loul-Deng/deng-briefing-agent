"""P1 checks that do not call the LLM: date, tool fields, pending calls, citation gap."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cite import check_briefing, collect_seen_urls, extract_md_urls  # noqa: E402
from history import mark_reported, reported_urls  # noqa: E402
from loop import _has_written_file, _pending_tool_calls, _tool_fields  # noqa: E402
from prompt import beijing_today, build_system_prompt, default_user_prompt  # noqa: E402


def test_beijing_today_crosses_utc_midnight() -> None:
    # 2026-09-28 16:30 UTC 在北京已是 9 月 29 日 00:30。
    instant = datetime(2026, 9, 28, 16, 30, tzinfo=ZoneInfo("UTC"))
    assert beijing_today(instant).isoformat() == "2026-09-29"


def test_default_prompt_uses_beijing_date(monkeypatch: pytest.MonkeyPatch) -> None:
    import prompt

    monkeypatch.setattr(prompt, "beijing_today", lambda now=None: __import__("datetime").date(2026, 9, 28))
    text = default_user_prompt()
    assert "2026-09-28" in text
    assert "2026-09-28" in build_system_prompt()


def test_tool_fields_ignore_tool_name() -> None:
    assert _tool_fields('{"query": "LLM agent memory", "limit": 5}') == {"query": "LLM agent memory"}
    assert _tool_fields('{"url": "https://arxiv.org/abs/1"}') == {"url": "https://arxiv.org/abs/1"}
    assert _tool_fields('{"path": "briefing.md", "content": "x"}') == {"path": "briefing.md"}
    assert _tool_fields("not-json") == {}


def test_pending_tool_calls_partial_batch() -> None:
    calls = [
        {"id": "a", "function": {"name": "web_search", "arguments": "{}"}},
        {"id": "b", "function": {"name": "fetch_url", "arguments": "{}"}},
    ]
    messages = [
        {"role": "assistant", "content": None, "tool_calls": calls},
        {"role": "tool", "tool_call_id": "a", "name": "web_search", "content": "{}"},
    ]
    pending = _pending_tool_calls(messages)
    assert [item["id"] for item in pending] == ["b"]


def test_pending_tool_calls_none_when_answered() -> None:
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "a", "function": {"name": "fetch_url", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "a", "name": "fetch_url", "content": "{}"},
    ]
    assert _pending_tool_calls(messages) == []


def test_has_written_file_uses_shape_not_name() -> None:
    search = [{"role": "tool", "name": "web_search", "content": json.dumps({"results": [{"url": "https://a.example"}]})}]
    assert _has_written_file(search) is False
    search.append(
        {
            "role": "tool",
            "name": "whatever",
            "content": json.dumps({"ok": True, "path": "E:/DENG/output/a.md", "relative": "output/a.md"}),
        }
    )
    assert _has_written_file(search) is True


def test_cite_marks_unseen_url_once(tmp_path: Path) -> None:
    seen = "https://arxiv.org/abs/2609.08149"
    unseen = "https://example.com/made-up"
    messages = [
        {
            "role": "tool",
            "content": json.dumps({"results": [{"url": seen + "/"}]}),
        },
        {
            "role": "tool",
            "content": json.dumps({"ok": True, "url": "https://github.com/org/repo", "path": "ignored"}),
        },
    ]
    assert seen in collect_seen_urls(messages)
    target = tmp_path / "briefing.md"
    target.write_text(f"见 [{seen}]({seen}) 和 {unseen}。\n", encoding="utf-8")
    first = check_briefing(target, messages)
    assert first["unchecked"] == [unseen]
    text = target.read_text(encoding="utf-8")
    assert text.count("## 未核对链接") == 1
    assert unseen in text
    second = check_briefing(target, messages)
    assert second["unchecked"] == [unseen]
    assert target.read_text(encoding="utf-8").count("## 未核对链接") == 1


def test_cite_leaves_file_when_every_url_was_seen(tmp_path: Path) -> None:
    url = "https://arxiv.org/abs/1"
    messages = [{"role": "tool", "content": json.dumps({"url": url})}]
    target = tmp_path / "briefing.md"
    body = f"摘要：{url}\n"
    target.write_text(body, encoding="utf-8")
    result = check_briefing(target, messages)
    assert result["unchecked"] == []
    assert target.read_text(encoding="utf-8") == body
    assert extract_md_urls(body) == [url]


def test_mark_reported_keeps_url_under_model_heading(tmp_path: Path) -> None:
    # 模型若自己写了「## 已报道」，程序不能把标题下面的链接切掉，否则历史命中会被丢掉。
    old_url = "https://arxiv.org/abs/2609.08149"
    (tmp_path / "old.md").write_text(f"昨天已报道 {old_url}\n", encoding="utf-8")
    target = tmp_path / "briefing.md"
    target.write_text(f"# 新简报\n\n## 已报道\n\n{old_url}\n", encoding="utf-8")
    messages = [{"role": "tool", "content": json.dumps({"results": []})}]
    check_briefing(target, messages)
    known = reported_urls(tmp_path, exclude=target)
    hits = mark_reported(target, known)
    text = target.read_text(encoding="utf-8")
    assert hits == [old_url]
    assert "以下链接已在更早的简报中出现" in text
    assert old_url in text.split("## 已报道", 1)[1]
