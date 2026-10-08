"""每天跑完写一份回执。人不盯终端时，打开 output/last-run.md 就知道成没成。"""

from __future__ import annotations

from pathlib import Path

# 模型和简报扫描都不能碰这两个名字，否则回执会被盖掉或被当成一篇简报。
LAST_RUN_NAME = "last-run.md"
_FAILED_PREFIX = "failed-"


def failed_name(day: str) -> str:
    """当天失败说明的文件名。一天一份，成功后由 write_receipt 删掉。"""
    return f"{_FAILED_PREFIX}{day}.md"


def is_receipt_name(name: str) -> bool:
    """last-run.md 和 failed-日期.md 都是程序的回执，不是简报。"""
    lower = Path(name).name.lower()
    return lower == LAST_RUN_NAME or (lower.startswith(_FAILED_PREFIX) and lower.endswith(".md"))


def write_receipt(
    root: str | Path,
    *,
    day: str,
    ok: bool,
    reason: str = "",
    briefing: str = "",
    unchecked: int = 0,
    reported: int = 0,
    end_reason: str = "",
    session_id: str = "",
) -> Path:
    """覆盖 last-run.md。失败再写 failed-日期.md；成功则删掉当天那份，避免早上还看着旧失败。"""
    folder = Path(root)
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["# 运行回执", "", f"- 日期：{day}", f"- 结果：{'成功' if ok else '失败'}"]
    if ok:
        lines.append(f"- 文件：{briefing}")
        lines.append(f"- 未核对：{unchecked}")
        lines.append(f"- 已报道：{reported}")
    else:
        lines.append(f"- 原因：{reason or 'unknown'}")
        # 空报仍有文件。把路径和条数留下，失败说明里能打开那份薄简报。
        if briefing:
            lines.append(f"- 文件：{briefing}")
            lines.append(f"- 未核对：{unchecked}")
            lines.append(f"- 已报道：{reported}")
    if end_reason:
        lines.append(f"- 结束原因：{end_reason}")
    if session_id:
        lines.append(f"- 会话：{session_id}")
    lines.append("")
    text = "\n".join(lines)
    last = folder / LAST_RUN_NAME
    last.write_text(text, encoding="utf-8")
    failed = folder / failed_name(day)
    if ok:
        if failed.is_file():
            failed.unlink()
    else:
        failed.write_text(text, encoding="utf-8")
    return last
