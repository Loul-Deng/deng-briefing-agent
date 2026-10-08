# 前沿简报 Agent（P0）

跟踪大模型 / Agent 相关论文与开源项目，整理成可核对的技术简报。这是一条**窄腰**实现：Loop 调度模型与工具，不在 Loop 里写死工具名。

## 能做什么

```text
python main.py
python main.py "过去一周 Agent 记忆或上下文相关的论文和开源项目，写成技术简报"
python main.py --resume 20260917_101500 "补充一篇最新的"
```

另一条入口是 MCP。外壳只提供 `run_briefing` 和 `resume_briefing`，里面调用的仍是上面这条 Agent。`web_search`、`fetch_url`、`write_file` 不对外。Cursor 项目配置在 `.cursor/mcp.json`。单独起服务：

```text
.\.venv\Scripts\python.exe mcp_server.py
```

不传参数时，按北京时间的当天日期生成默认简报任务。每天 08:00 由 Windows 任务计划调用无参数的 `python main.py`，不在 Loop 里空转等待。

产出：

- `output/*.md`：简报，文件名含会话 id（`briefing-YYYYMMDD_HHMMSS.md`）。同一路径已存在时写成 `stem-2.md`，不覆盖。`output/index.md` 是索引，由程序重写。`output/last-run.md` 是最近一次回执（路径、未核对条数、已报道条数）。失败时另写 `output/failed-日期.md`，进程以退出码 1 结束；当天成功后删掉这份失败说明。写出了文件但没有读到任何页面（空报）同样算失败。
- 写完后程序核对正文链接。对不上工具返回的，文末追加「未核对链接」。和历史简报是同一篇的（arXiv id 或仓库名相同，不要求 URL 全文一致），文末追加「已报道」。
- `sessions/<id>.jsonl`：完整 messages，可 `--resume`
- `traces/<id>.jsonl`：llm / tool / cite / end 事件。llm 事件含 token，tool 事件含 query、url 或 path，以及 ok

## 模块

| 文件 | 职责 |
|------|------|
| `src/loop.py` | while：调模型 → 若有 tool_calls 则 `registry.call` → 回填 messages |
| `mcp_server.py` | MCP 外壳：只暴露跑完整 Agent 和续跑，stdio |
| `src/llm.py` | DeepSeek OpenAI 兼容适配；换模型只改 `config.yaml` |
| `src/registry.py` | `register` / `list_schemas` / `call` |
| `src/prompt.py` | 固定 system、北京日期、会话文件名、已报道链接、收尾指令 |
| `src/cite.py` | 写盘后核对链接，未出现在工具返回里的 URL 追加到文末 |
| `src/history.py` | 读历史简报 URL、按论文 id / 仓库名标注已报道、重写 `output/index.md` |
| `src/receipt.py` | 写 `last-run.md`；失败时写 `failed-日期.md` |
| `src/observe.py` | 模型已经看过的工具结果收成标题、URL 和两句摘要 |
| `src/session.py` | 会话 JSONL |
| `src/trace.py` | 追踪 JSONL |
| `src/tools/web_search.py` | 对外一个工具；对内并行 DDG + arXiv + GitHub + HF Daily，再去重 |
| `src/sources/` | 各信息源适配器 + `dedup.py` |
| `src/tools/fetch_url.py` | HTML 转纯文本，截断；拒绝 PDF |
| `src/tools/write_file.py` | 只允许写到 `output/`；已存在则改名；拒绝 `index.md` |

密钥只放 `.env`（`DEEPSEEK_API_KEY`）。信息源开关在 `config.yaml` 的 `web.sources`，**不要做成「注册 API Key」工具**。

`web_search` 一次调用会同时打：

- DuckDuckGo（新闻/博客）
- arXiv API（论文）
- GitHub Search + GitHub Trending（仓库）
- Hugging Face Daily Papers（当日热门论文）

然后按 `arxiv:id` / `repo:owner/name` / 规范化 URL 去重。单源失败只记入 `source_errors`，其它源照常返回。

## 退出条件

模型不再返回 `tool_calls`，或达到 `agent.max_turns`（默认 12），或用尽预算。预算是 `agent.max_minutes`（默认 8 分钟墙钟）和 `agent.max_tokens`（默认 150000，累计 prompt + completion）。`history.url_limit`（默认 40）限制写进 system 的历史链接条数。

最后一两轮仍未写盘（第一轮除外），或轮数/预算用尽仍没有文件时，会追加一条收尾指令再问一轮（工具仍可用）。预算用尽的 `end_reason` 是 `budget`，轮数用尽是 `wrap_up`。问下一轮之前，更早的工具原文会收短；刚返回、模型还没读过的那一批保持全文。

终端在每次工具执行之后打印一行，例如 `[tool] web_search ok=true query=LLM agent memory`。`ok` 只有执行完才有，所以打印在 `registry.call` 之后。

## 每天 08:00

任务名 `DENG-daily-briefing`。工作目录是仓库根，这样才能读到 `.env`。错过八点（合盖）会在醒来后尽快补跑。用的是当前登录用户，不用 SYSTEM。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-daily-task.ps1
Unregister-ScheduledTask -TaskName DENG-daily-briefing -Confirm:$false
```

## 安装

```powershell
cd E:\DENG
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
python main.py
```

## 评测

`tests/test_eval.py` 打了 `live` 标记，会调用真实 DeepSeek。没有 `DEEPSEEK_API_KEY` 时整文件跳过。

```powershell
pytest tests
pytest tests -m "not live"
```

只要本地规则、不花钱时用第二条。评测自己把 `max_turns` 收到 4、`max_minutes` 收到 3，不改 `config.yaml` 的日常默认值。

## 明确不做

P1 已做：无参数默认简报、临近轮数上限时收尾写盘、写盘后标注未核对链接、终端和 trace 打印 query / url / path / ok、每天 08:00 任务计划。

P2 已做：历史链接写入 system 并在文末标注已报道、文件名含会话 id 且不覆盖旧文件、`output/index.md`、时间与 token 预算、十道真实接口评测。

接着做了三件：运行回执（成功写路径和条数，失败写当天说明并退出码 1；空报也算失败）、同一篇论文或仓库只算一次、旧工具观察收短。另有 MCP 外壳：外面用工具调用整个 Agent，里面仍是原来的循环。

下面这些仍不做：多 Agent、把内部工具拆成 MCP、Browser、整段上下文压缩、Web 壳、Permission Gate、PDF 解析。
