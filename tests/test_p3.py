"""回执、同一篇去重、旧观察收短。不调用模型。"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cite import collect_seen_urls, pages_read  # noqa: E402
from history import mark_reported, reported_urls  # noqa: E402
from observe import shorten_seen_tools, two_sentences  # noqa: E402
from receipt import failed_name, write_receipt  # noqa: E402
from tools.write_file import write_file  # noqa: E402

_ABS = "https://arxiv.org/abs/2609.08149"
_PDF = "https://arxiv.org/pdf/2609.08149.pdf"
_OTHER = "https://arxiv.org/abs/1111.22222"
_REPO = "https://github.com/mem0ai/mem0"
_README = "https://github.com/mem0ai/mem0/blob/main/README.md"


def test_two_sentences_keeps_a_pair() -> None:
    text = two_sentences("第一句。第二句。第三句不该留下。")
    assert text == "第一句。第二句。"
    assert "第三句" not in text


def test_pdf_and_abs_are_the_same_paper(tmp_path: Path) -> None:
    # 旧简报写的是 pdf，新简报写 abs。身份证相同，就要标已报道。
    (tmp_path / "old.md").write_text(f"昨天 {_PDF}\n", encoding="utf-8")
    target = tmp_path / "briefing.md"
    target.write_text(f"今天 {_ABS}\n", encoding="utf-8")
    known = reported_urls(tmp_path, exclude=target)
    assert known == [_PDF]
    hits = mark_reported(target, known)
    assert hits == [_ABS]
    assert "以下链接已在更早的简报中出现" in target.read_text(encoding="utf-8")


def test_different_arxiv_ids_stay_distinct(tmp_path: Path) -> None:
    (tmp_path / "old.md").write_text(f"昨天 {_PDF}\n", encoding="utf-8")
    target = tmp_path / "briefing.md"
    target.write_text(f"今天 {_OTHER}\n", encoding="utf-8")
    hits = mark_reported(target, reported_urls(tmp_path, exclude=target))
    assert hits == []
    assert "已报道" not in target.read_text(encoding="utf-8")


def test_repo_root_and_readme_are_the_same_repo(tmp_path: Path) -> None:
    (tmp_path / "old.md").write_text(f"仓库 {_REPO}\n", encoding="utf-8")
    target = tmp_path / "briefing.md"
    target.write_text(f"说明 {_README}\n", encoding="utf-8")
    hits = mark_reported(target, reported_urls(tmp_path, exclude=target))
    assert hits == [_README]


def test_receipt_files_are_not_history(tmp_path: Path) -> None:
    (tmp_path / "last-run.md").write_text(f"回执里提到 {_ABS}\n", encoding="utf-8")
    (tmp_path / "failed-2026-09-29.md").write_text(f"失败里提到 {_OTHER}\n", encoding="utf-8")
    assert reported_urls(tmp_path) == []


def test_success_receipt_clears_today_failure(tmp_path: Path) -> None:
    day = "2026-09-29"
    (tmp_path / failed_name(day)).write_text("旧失败\n", encoding="utf-8")
    write_receipt(
        tmp_path,
        day=day,
        ok=True,
        briefing="output/briefing.md",
        unchecked=2,
        reported=1,
        end_reason="no_tool_calls",
        session_id="sid",
    )
    text = (tmp_path / "last-run.md").read_text(encoding="utf-8")
    assert "结果：成功" in text
    assert "output/briefing.md" in text
    assert "未核对：2" in text
    assert "已报道：1" in text
    assert not (tmp_path / failed_name(day)).exists()


def test_failure_receipt_is_its_own_file(tmp_path: Path) -> None:
    day = "2026-09-29"
    write_receipt(tmp_path, day=day, ok=False, reason="no written file", end_reason="wrap_up", session_id="sid")
    failed = (tmp_path / failed_name(day)).read_text(encoding="utf-8")
    assert "结果：失败" in failed
    assert "no written file" in failed
    assert failed == (tmp_path / "last-run.md").read_text(encoding="utf-8")


def test_write_file_rejects_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.write_file as wf

    monkeypatch.setattr(wf, "output_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="last-run.md"):
        write_file("last-run.md", "不许写")
    with pytest.raises(ValueError, match="failed-2026-09-29.md"):
        write_file("failed-2026-09-29.md", "不许写")


def test_old_fetch_is_shortened_latest_stays_full() -> None:
    page = "第一句。第二句。第三句不该再送给模型。" + ("尾部" * 80)
    latest = "刚抓到的全文应该原样留下。" * 10
    messages = [
        {"role": "assistant", "content": None, "tool_calls": []},
        {"role": "tool", "content": json.dumps({"ok": True, "url": _ABS, "text": page}, ensure_ascii=False)},
        {"role": "assistant", "content": "继续"},
        {"role": "tool", "content": json.dumps({"ok": True, "url": _OTHER, "text": latest}, ensure_ascii=False)},
    ]
    shorten_seen_tools(messages)
    old = json.loads(messages[1]["content"])
    fresh = json.loads(messages[3]["content"])
    assert old["shortened"] is True
    assert old["text"] == "第一句。第二句。"
    assert old["url"] == _ABS
    assert fresh["text"] == latest
    assert _ABS in collect_seen_urls(messages)
    assert _OTHER in collect_seen_urls(messages)


def test_main_failure_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import main as cli

    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(cli, "output_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "beijing_today", lambda: date(2026, 9, 29))
    monkeypatch.setattr(cli, "run_agent", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("key missing")))
    assert cli.main() == 1
    text = (tmp_path / "failed-2026-09-29.md").read_text(encoding="utf-8")
    assert "key missing" in text
    assert "结果：失败" in text


def test_main_success_records_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import main as cli

    monkeypatch.setattr(sys, "argv", ["main.py", "写一份"])
    monkeypatch.setattr(cli, "output_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "beijing_today", lambda: date(2026, 9, 29))
    (tmp_path / "failed-2026-09-29.md").write_text("旧失败\n", encoding="utf-8")

    def fake_run(*_a, **_k):
        return {
            "session_id": "sid",
            "end_reason": "no_tool_calls",
            "final_text": "写好了",
            "cite": {
                "skipped": False,
                "path": str(tmp_path / "briefing-sid.md"),
                "unchecked": ["https://example.com/a"],
                "reported": [_ABS, _REPO],
                "pages_read": 1,
            },
        }

    monkeypatch.setattr(cli, "run_agent", fake_run)
    assert cli.main() == 0
    text = (tmp_path / "last-run.md").read_text(encoding="utf-8")
    assert "结果：成功" in text
    assert "未核对：1" in text
    assert "已报道：2" in text
    assert "output/briefing-sid.md" in text
    assert not (tmp_path / "failed-2026-09-29.md").exists()


def test_main_without_file_is_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import main as cli

    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(cli, "output_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "beijing_today", lambda: date(2026, 9, 29))
    monkeypatch.setattr(
        cli,
        "run_agent",
        lambda *_a, **_k: {
            "session_id": "sid",
            "end_reason": "wrap_up",
            "final_text": "",
            "cite": {"skipped": True, "reason": "no written file", "unchecked": [], "reported": []},
        },
    )
    assert cli.main() == 1
    assert "no written file" in (tmp_path / "failed-2026-09-29.md").read_text(encoding="utf-8")


def test_pages_read_counts_only_opened_pages() -> None:
    # 搜索摘要、写文件、抓取失败都不算读过。有正文的打开才算，收短后的正文也算。
    messages = [
        {"role": "tool", "content": json.dumps({"query": "llm", "results": [{"url": _ABS, "title": "t"}]})},
        {"role": "tool", "content": json.dumps({"ok": True, "path": "E:/out/a.md", "relative": "output/a.md"})},
        {"role": "tool", "content": json.dumps({"error": "HTTP 404", "url": _OTHER})},
        {"role": "tool", "content": json.dumps({"ok": True, "url": _ABS, "text": "  "})},
        {"role": "tool", "content": json.dumps({"ok": True, "url": _ABS, "text": "第一句。", "shortened": True})},
    ]
    assert pages_read(messages) == 1


def test_main_empty_report_is_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import main as cli

    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(cli, "output_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "beijing_today", lambda: date(2026, 9, 29))
    monkeypatch.setattr(
        cli,
        "run_agent",
        lambda *_a, **_k: {
            "session_id": "sid",
            "end_reason": "no_tool_calls",
            "final_text": "未读到",
            "cite": {
                "skipped": False,
                "path": str(tmp_path / "briefing-sid.md"),
                "unchecked": [],
                "reported": [],
                "pages_read": 0,
            },
        },
    )
    assert cli.main() == 1
    text = (tmp_path / "failed-2026-09-29.md").read_text(encoding="utf-8")
    assert "结果：失败" in text
    assert "空报：没有读到任何页面" in text
    assert "output/briefing-sid.md" in text
    assert "结果：成功" not in (tmp_path / "last-run.md").read_text(encoding="utf-8")
