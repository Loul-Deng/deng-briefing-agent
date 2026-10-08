"""拼出本轮固定的 system prompt，以及每天默认任务、临近轮数上限时的收尾指令。"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# 简报按北京时间的日历日，不跟电脑当前时区走。八点启动是任务计划的事，这里只负责「今天是哪一天」。
BEIJING = ZoneInfo("Asia/Shanghai")

SYSTEM_PROMPT = """你是前沿技术简报助手。任务是跟踪大模型 / Agent 相关的论文与开源项目，整理成一份可核对的技术简报。

今天日期：{today}

工作顺序（必须遵守）：
1. 先用 web_search 找候选。该工具会同时查 DuckDuckGo、arXiv、GitHub 搜索/Trending、Hugging Face Daily Papers，并已按论文 id / 仓库名去重。结果里的 sources 字段表示命中了哪些源。
2. 再用 fetch_url 打开其中最相关的若干链接，阅读摘要或 README（不要猜测未读过的内容）。GitHub 仓库页超时就改抓 raw.githubusercontent.com 的 README。
3. 最后用 write_file 把简报写到 output/briefing-{session_id}.md。不要用只有日期的文件名。

简报正文至少包含：
- 日期与主题范围
- 论文 1～3 篇：标题、链接、一句话贡献
- 开源项目 1～3 个：仓库、最近动向
- 来源 URL 列表：每一条结论都必须能追溯到你 search/fetch 过的链接；禁止无链接结论

已报道链接（不要当成新发现；若仍提及，在该条旁写「已报道」）：
{reported_block}

约束：
- 不要编造论文标题、作者、分数或 star 数。读不到就写「未读到」。
- arXiv PDF 不要 fetch；改抓 HTML 摘要页。
- write_file 只能写到 output/ 目录，不要写 index.md、last-run.md、failed-日期.md。
- 完成写文件后，用简短中文向用户确认文件路径。
"""

# 轮数快用尽时塞进 messages。仍然允许工具，但只要求写文件——禁掉工具就写不了盘。
WRAP_UP_PROMPT = (
    "停止继续搜索和打开新链接。"
    "请立刻用已经拿到的材料调用 write_file，把简报写到 output/ 下。"
    "材料不够的地方写「未读到」，不要再调用搜索或抓取。"
)


def beijing_today(now: datetime | None = None) -> date:
    """返回北京时间的日历日期。传入 now 只为测试，正式运行不传。"""
    if now is None:
        current = datetime.now(BEIJING)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=BEIJING)
    else:
        current = now.astimezone(BEIJING)
    return current.date()


def build_system_prompt(session_id: str | None = None, reported: list[str] | None = None) -> str:
    """填入北京日期、本次会话文件名，以及历史已报道链接。"""
    today = beijing_today().isoformat()
    if reported:
        block = "\n".join(f"- {url}" for url in reported)
    else:
        block = "（无）"
    return SYSTEM_PROMPT.format(
        today=today,
        session_id=session_id or "SESSION",
        reported_block=block,
    )


def default_user_prompt(now: datetime | None = None) -> str:
    """不传命令行参数时的默认任务。日期写进句子，避免模型用错「今天」。"""
    today = beijing_today(now).isoformat()
    return f"今天是 {today}。请写一份大模型 / Agent 前沿论文与开源项目的技术简报。"
