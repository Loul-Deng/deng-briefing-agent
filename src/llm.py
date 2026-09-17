"""OpenAI 兼容的 LLM 适配器。第一版只接 DeepSeek。

换模型只改 config.yaml / .env，不要改 Loop。
"""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


def create_client(cfg: dict[str, Any]) -> OpenAI:
    """用环境变量里的密钥构造客户端。密钥缺失时立刻失败，避免带着空 key 空转。"""
    model_cfg = cfg.get("model") or {}
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is missing. Copy .env.example to .env and fill it in.")
    base_url = os.getenv("DEEPSEEK_BASE_URL") or model_cfg.get("base_url") or "https://api.deepseek.com/v1"
    return OpenAI(api_key=api_key, base_url=base_url)


def chat(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> Any:
    """发起一轮 chat.completions。有 tools 时让模型自己决定是否 tool_choice=auto。"""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    completion = client.chat.completions.create(**kwargs)
    return completion.choices[0].message
