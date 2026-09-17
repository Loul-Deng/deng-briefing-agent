"""工具注册表：名字 → JSON schema + Python 处理函数。

Loop 只允许调用 list_schemas() 和 call()，禁止写 if name == "web_search"。
Hermes 的 tools/registry.py 也是这个思路，这里是缩小版。
"""

from __future__ import annotations

import json
from typing import Any, Callable


class ToolRegistry:
    """内存里的一张表。register 登记，call 按名字分发。"""

    def __init__(self) -> None:
        """创建空表。"""
        self._tools: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., str],
    ) -> None:
        """登记一个工具。同名重复登记会报错，避免悄悄覆盖。"""
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = {
            "description": description,
            "parameters": parameters,
            "handler": handler,
        }

    def list_schemas(self) -> list[dict[str, Any]]:
        """生成 OpenAI / DeepSeek 兼容的 tools 参数，发给模型看。"""
        schemas = []
        for name, spec in self._tools.items():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": spec["description"],
                        "parameters": spec["parameters"],
                    },
                }
            )
        return schemas

    def call(self, name: str, arguments: str | dict[str, Any] | None) -> str:
        """执行工具。参数解析失败或 handler 抛错时返回 JSON 错误串，不把 Loop 打崩。"""
        spec = self._tools.get(name)
        if spec is None:
            return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
        try:
            if arguments is None or arguments == "":
                args: dict[str, Any] = {}
            elif isinstance(arguments, dict):
                args = arguments
            else:
                args = json.loads(arguments)
            if not isinstance(args, dict):
                return json.dumps({"error": "arguments must be a JSON object"}, ensure_ascii=False)
            result = spec["handler"](**args)
            if result is None:
                return ""
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False)
        except TypeError as exc:
            return json.dumps({"error": f"bad arguments for {name}: {exc}"}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 — 工具失败必须回到模型，而不是退出进程
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)


def build_registry() -> ToolRegistry:
    """启动时登记 P0 三件套。新工具在这里多写一行 register，Loop 不用改。"""
    from tools.fetch_url import register as register_fetch
    from tools.web_search import register as register_search
    from tools.write_file import register as register_write

    registry = ToolRegistry()
    register_write(registry)
    register_fetch(registry)
    register_search(registry)
    return registry
