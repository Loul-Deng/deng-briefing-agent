"""项目根目录、config.yaml 与 .env 加载。密钥只从环境变量读，不进工具参数。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# src/ 的上一级就是仓库根目录 E:\DENG
ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict[str, Any]:
    """读取 .env 和 config.yaml。每次调用都重新读文件，改配置不用重启也方便调试。"""
    load_dotenv(ROOT / ".env")
    path = ROOT / "config.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def output_dir(cfg: dict[str, Any] | None = None) -> Path:
    """简报落盘目录（默认 <仓库>/output），write_file 的沙箱根就是这里。"""
    cfg = cfg if cfg is not None else load_config()
    rel = cfg.get("output_dir") or "output"
    return (ROOT / rel).resolve()
