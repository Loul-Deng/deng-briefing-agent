"""去重与信息源相关测试，不调用大模型。"""

from __future__ import annotations

from sources.dedup import canonical_key, merge_hits  # noqa: E402


def test_arxiv_abs_and_pdf_are_same_paper() -> None:
    """abs 页和 pdf 链应合成一条。"""
    a = {"title": "Foo", "url": "https://arxiv.org/abs/2603.07670", "snippet": "a", "sources": ["arxiv"]}
    b = {"title": "Foo", "url": "https://arxiv.org/pdf/2603.07670.pdf", "snippet": "longer abstract text", "sources": ["ddgs"]}
    merged = merge_hits([a, b])
    assert len(merged) == 1
    assert merged[0]["arxiv_id"] == "2603.07670"
    assert set(merged[0]["sources"]) == {"arxiv", "ddgs"}
    assert merged[0]["snippet"] == "longer abstract text"


def test_github_repo_url_variants() -> None:
    """仓库首页和 README 页应合成一个 repo。"""
    a = {"title": "mem0", "url": "https://github.com/mem0ai/mem0", "snippet": "", "sources": ["github_trending"]}
    b = {"title": "mem0", "url": "https://github.com/mem0ai/mem0/blob/main/README.md", "snippet": "memory layer", "sources": ["ddgs"]}
    merged = merge_hits([a, b])
    assert len(merged) == 1
    assert merged[0]["repo"] == "mem0ai/mem0"
    assert "github_trending" in merged[0]["sources"] and "ddgs" in merged[0]["sources"]


def test_different_papers_stay_separate() -> None:
    """不同 arXiv id 不能被并掉。"""
    a = {"title": "A", "url": "https://arxiv.org/abs/2603.07670", "snippet": "", "sources": ["arxiv"]}
    b = {"title": "B", "url": "https://arxiv.org/abs/2609.03340", "snippet": "", "sources": ["hf_daily"]}
    merged = merge_hits([a, b])
    assert len(merged) == 2


def test_bracket_arxiv_id_in_ddg_title() -> None:
    """DDG 常用 [2502.12110] 标题，应识别成论文并和 abs 链接合并。"""
    a = {"title": "[2502.12110] A-MEM", "url": "https://arxiv.org/html/2502.12110", "snippet": "ddg", "sources": ["ddgs"]}
    b = {"title": "A-MEM", "url": "https://arxiv.org/abs/2502.12110", "snippet": "arxiv abs", "sources": ["arxiv"]}
    merged = merge_hits([a, b])
    assert len(merged) == 1
    assert merged[0]["kind"] == "paper"
    assert set(merged[0]["sources"]) == {"ddgs", "arxiv"}


def test_canonical_key_strips_version() -> None:
    """v1 / v2 视为同一篇。"""
    item = {"url": "http://arxiv.org/abs/2603.07670v2", "title": "x"}
    assert canonical_key(item) == "arxiv:2603.07670"


def test_web_search_schema_still_one_tool() -> None:
    """模型侧仍然只有一个 web_search，固定源是内部实现。"""
    from registry import build_registry

    names = {item["function"]["name"] for item in build_registry().list_schemas()}
    assert names == {"web_search", "fetch_url", "write_file"}
    desc = next(s["function"]["description"] for s in build_registry().list_schemas() if s["function"]["name"] == "web_search")
    assert "arXiv" in desc or "arxiv" in desc.lower()
