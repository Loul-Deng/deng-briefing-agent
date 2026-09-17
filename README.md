# 前沿简报 Agent（P0）

跟踪大模型 / Agent 相关论文与开源项目，整理成可核对的技术简报。这是一条**窄腰**实现：Loop 调度模型与工具，不在 Loop 里写死工具名。

## 能做什么

```text
python main.py "过去一周 Agent 记忆或上下文相关的论文和开源项目，写成技术简报"
python main.py --resume 20260917_101500 "补充一篇最新的"
```

产出：

- `output/*.md`：简报
- `sessions/<id>.jsonl`：完整 messages，可 `--resume`
- `traces/<id>.jsonl`：llm / tool / end 事件（面试时对着这条讲）

## 模块

| 文件 | 职责 |
|------|------|
| `src/loop.py` | while：调模型 → 若有 tool_calls 则 `registry.call` → 回填 messages |
| `src/llm.py` | DeepSeek OpenAI 兼容适配；换模型只改 `config.yaml` |
| `src/registry.py` | `register` / `list_schemas` / `call` |
| `src/prompt.py` | 固定 system：先搜再读再写，结论必须带链接 |
| `src/session.py` | 会话 JSONL |
| `src/trace.py` | 追踪 JSONL |
| `src/tools/web_search.py` | 对外一个工具；对内并行 DDG + arXiv + GitHub + HF Daily，再去重 |
| `src/sources/` | 各信息源适配器 + `dedup.py` |
| `src/tools/fetch_url.py` | HTML 转纯文本，截断；拒绝 PDF |
| `src/tools/fetch_url.py` | HTML 转纯文本，截断；拒绝 PDF |
| `src/tools/write_file.py` | 只允许写到 `output/` |

密钥只放 `.env`（`DEEPSEEK_API_KEY`）。信息源开关在 `config.yaml` 的 `web.sources`，**不要做成「注册 API Key」工具**。

`web_search` 一次调用会同时打：

- DuckDuckGo（新闻/博客）
- arXiv API（论文）
- GitHub Search + GitHub Trending（仓库）
- Hugging Face Daily Papers（当日热门论文）

然后按 `arxiv:id` / `repo:owner/name` / 规范化 URL 去重。单源失败只记入 `source_errors`，其它源照常返回。

## 退出条件

模型不再返回 `tool_calls`，或达到 `agent.max_turns`（默认 12）。

## 安装

```powershell
cd E:\DENG
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
python main.py "写一份本周 Agent 记忆相关简报"
```

## 明确不做（P0）

多 Agent、MCP、Browser、跨会话 Memory、上下文压缩、Permission Gate、PDF 解析。
