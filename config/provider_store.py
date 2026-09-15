"""供应商 API Key 的按需持久化存储。

将各供应商的 api_key 独立保存到 ``APP_ROOT/providers.json``（JSON 文件，
可写数据根，打包后为 exe 同级，源码运行为项目根），使每个供应商拥有
独立的 key，且重启不丢失。不在 .env 中混存，避免污染环境变量配置。

约定：
- 每个供应商一条记录：``{ 供应商名: api_key }``。
- 读取顺序：运行时持久化值优先于 .env 环境变量（env 作为未输入时的兜底）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.utils.paths import APP_ROOT

# api_key 持久化文件（与 .env 同级，可写）
_KEYS_FILE = APP_ROOT / "providers.json"


def load_api_keys() -> dict[str, str]:
    """读取全部已保存的 api_key，按供应商名映射。文件不存在或损坏时返回空字典。"""
    try:
        with open(_KEYS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, str)}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_api_key(provider_name: str, api_key: str) -> None:
    """保存某个供应商的 api_key（空值表示清除该记录）。"""
    keys = load_api_keys()
    if api_key:
        keys[provider_name] = api_key
    else:
        keys.pop(provider_name, None)
    try:
        with open(_KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, ensure_ascii=False, indent=2)
    except OSError:  # noqa: BLE001 - 写失败不致命，仅日志
        from app.utils.logger import get_logger

        get_logger(__name__).warning("保存供应商 API Key 失败: %s", _KEYS_FILE)


def get_api_key(provider_name: str, env_default: str = "") -> str:
    """返回某供应商的 api_key：优先运行时保存值，其次 .env 兜底。"""
    saved = load_api_keys().get(provider_name, "")
    return saved or env_default
