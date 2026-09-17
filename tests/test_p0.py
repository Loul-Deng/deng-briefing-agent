"""Sandbox and registry tests that do not call the LLM."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from registry import ToolRegistry, build_registry  # noqa: E402
from tools.write_file import write_file  # noqa: E402


def test_write_file_rejects_parent_escape() -> None:
    with pytest.raises(ValueError, match="parent directory"):
        write_file("../secrets.txt", "nope")


def test_write_file_rejects_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        write_file(str(ROOT / "secrets.txt"), "nope")


def test_write_file_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.write_file as wf

    monkeypatch.setattr(wf, "output_dir", lambda: tmp_path)
    payload = json.loads(write_file("briefing.md", "# hi\n"))
    assert payload["ok"] is True
    assert (tmp_path / "briefing.md").read_text(encoding="utf-8") == "# hi\n"


def test_registry_unknown_tool() -> None:
    reg = ToolRegistry()
    out = json.loads(reg.call("nope", "{}"))
    assert "unknown tool" in out["error"]


def test_registry_does_not_hardcode_names() -> None:
    reg = build_registry()
    names = {item["function"]["name"] for item in reg.list_schemas()}
    assert names == {"web_search", "fetch_url", "write_file"}
    echo = json.loads(reg.call("echo", '{"text":"x"}'))
    assert "unknown tool" in echo["error"]
