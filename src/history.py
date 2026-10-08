"""跨日去重与简报索引。程序自己读历史文件，不做成模型可以跳过的工具。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cite import UNCHECKED_HEADING, extract_md_urls
from receipt import is_receipt_name
from sources.dedup import canonical_key

# 索引由 update_index 重写。模型写这个名字会被 write_file 拒绝。
INDEX_NAME = "index.md"
REPORTED_HEADING = "## 已报道"


def is_program_markdown(name: str) -> bool:
    """索引和回执由程序重写。扫描历史、列索引、模型写文件时都要跳过。"""
    lower = Path(name).name.lower()
    return lower == INDEX_NAME or is_receipt_name(lower)


def identity_key(url: str) -> str:
    """和 web_search 同一套身份证。abs / pdf / html 的同一篇 arXiv 会得到同一把键。"""
    return canonical_key({"url": url})


def article_body(text: str) -> str:
    """去掉文末由程序追加的小节，保留模型写在正文里的「已报道」标题。

    只认程序自己的引导句，避免模型写了同名标题时把链接从正文里切掉。
    """
    markers = (
        f"\n{UNCHECKED_HEADING}",
        f"\n{REPORTED_HEADING}\n\n以下链接已在更早的简报中出现",
    )
    cut = len(text)
    for marker in markers:
        index = text.find(marker)
        if index != -1:
            cut = min(cut, index)
    if text.startswith(UNCHECKED_HEADING):
        return ""
    return text[:cut].rstrip()


def reported_urls(output_dir: str | Path, limit: int = 40, exclude: str | Path | None = None) -> list[str]:
    """按修改时间从新到旧收集历史简报里的 URL。同一篇只留一条，最多 limit 条。

    exclude 用来跳过「刚刚这份」：它自己的链接不能算已经报道过。
    去重用 identity_key，不比完整字符串，所以 pdf 和 abs 不会占两个名额。
    """
    root = Path(output_dir)
    if not root.is_dir() or limit <= 0:
        return []
    skipped = Path(exclude).resolve() if exclude else None
    files = []
    for path in root.glob("*.md"):
        if is_program_markdown(path.name):
            continue
        if skipped is not None and path.resolve() == skipped:
            continue
        files.append(path)
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    found: list[str] = []
    seen: set[str] = set()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for url in extract_md_urls(article_body(text)):
            key = identity_key(url)
            if key in seen:
                continue
            seen.add(key)
            found.append(url)
            if len(found) >= limit:
                return found
    return found


def mark_reported(path: str | Path, known: list[str] | set[str]) -> list[str]:
    """正文里和历史是同一篇的，追加「已报道」。没有命中就不改文件；已有小节则整节重写，不叠两层。

    比对的是身份证，不是整段 URL。旧简报里的 pdf 链接和新简报里的 abs 链接算同一篇。
    """
    target = Path(path)
    if not target.is_file():
        return []
    original = target.read_text(encoding="utf-8")
    body = article_body(original)
    known_keys = {identity_key(url) for url in known}
    hits = [url for url in extract_md_urls(body) if identity_key(url) in known_keys]
    if not hits and REPORTED_HEADING not in original:
        return []

    unchecked = _unchecked_section(original)
    parts = [body]
    if unchecked:
        parts.append("\n\n" + unchecked.rstrip())
    if hits:
        lines = "\n".join(f"- {url}" for url in hits)
        parts.append(
            f"\n\n{REPORTED_HEADING}\n\n"
            "以下链接已在更早的简报中出现：\n\n"
            f"{lines}\n"
        )
    else:
        parts.append("\n")
    target.write_text("".join(parts), encoding="utf-8")
    return hits


def _unchecked_section(text: str) -> str:
    """保留 cite 刚写上的未核对小节。已报道小节由本次重写，这里丢掉。"""
    index = text.find(UNCHECKED_HEADING)
    if index == -1:
        return ""
    chunk = text[index:]
    reported_at = chunk.find("\n" + REPORTED_HEADING)
    if reported_at != -1:
        chunk = chunk[:reported_at]
    return chunk.strip()


def update_index(output_dir: str | Path) -> Path:
    """重写 output/index.md，按修改时间列出简报。没有新文件也刷新，让目录和索引一致。"""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    files = [path for path in root.glob("*.md") if not is_program_markdown(path.name)]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    lines = ["# 简报索引", ""]
    for path in files:
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(f"- {stamp} [{path.name}]({path.name})")
    lines.append("")
    index = root / INDEX_NAME
    index.write_text("\n".join(lines), encoding="utf-8")
    return index
