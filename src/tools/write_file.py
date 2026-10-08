"""write_file: only under project output/. No `..`, no absolute paths."""

from __future__ import annotations

import json
from pathlib import Path

from config import output_dir
from history import is_program_markdown
from registry import ToolRegistry


def _safe_output_path(raw: str) -> Path:
    """把模型给的相对路径限制在 output/ 里。绝对路径和 '..' 一律拒绝。"""
    if not raw or not str(raw).strip():
        raise ValueError("path is empty")
    p = Path(str(raw).strip())
    if p.is_absolute() or p.drive:
        raise ValueError("absolute paths are not allowed")
    parts = [part for part in p.parts if part not in ("/", "\\")]
    if parts and parts[0] == "output":
        parts = parts[1:]
    if not parts:
        raise ValueError("path is empty after stripping output/")
    if any(part == ".." for part in parts):
        raise ValueError("parent directory traversal is not allowed")
    out = output_dir().resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolved = (out.joinpath(*parts)).resolve()
    try:
        resolved.relative_to(out)
    except ValueError as exc:
        raise ValueError("path escapes output/") from exc
    return resolved


def _unused_path(target: Path) -> Path:
    """目标已存在时改成 stem-2.md、stem-3.md。不信任模型会自己换文件名。"""
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    number = 2
    while True:
        candidate = target.parent / f"{stem}-{number}{suffix}"
        if not candidate.exists():
            return candidate
        number += 1


def write_file(path: str, content: str) -> str:
    """写入 UTF-8 文本。已存在的文件不覆盖。索引和回执由程序维护，模型不能写。"""
    target = _safe_output_path(path)
    # 这些文件每次跑完会被程序重写。交给模型就会把回执盖成简报。
    if is_program_markdown(target.name):
        raise ValueError(f"{target.name} is maintained by the program")
    target = _unused_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    target.write_text(text, encoding="utf-8")
    rel = target.relative_to(output_dir().resolve())
    return json.dumps(
        {
            "ok": True,
            "path": str(target),
            "relative": str(Path("output") / rel).replace("\\", "/"),
            "bytes": target.stat().st_size,
        },
        ensure_ascii=False,
    )


def register(registry: ToolRegistry) -> None:
    """把 write_file 登记进注册表。"""
    registry.register(
        name="write_file",
        description=(
            "Write a UTF-8 text file under the project's output/ directory. "
            "Use the session filename from the system prompt, e.g. briefing-20260928_164000.md. "
            "Existing files are not overwritten. "
            "index.md, last-run.md, and failed-YYYY-MM-DD.md are rejected. "
            "Absolute paths and '..' are rejected."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative filename under output/, e.g. briefing.md",
                },
                "content": {
                    "type": "string",
                    "description": "Full file contents to write.",
                },
            },
            "required": ["path", "content"],
        },
        handler=write_file,
    )
