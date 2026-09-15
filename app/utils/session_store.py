"""会话持久化存储层：每个会话一个 JSON 文件，位于 APP_ROOT/sessions/。

文件结构::

    {
        "id", "title", "updated_at", "messages": [[role, text], ...]
    }

本层与 UI 完全解耦（不 import 任何控件），只负责磁盘读写，便于单独测试。
由 MainWindow 在启动加载、会话变更后保存、退出兜底时调用。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.utils.logger import get_logger
from app.utils.paths import APP_ROOT

logger = get_logger(__name__)

SESSIONS_DIR = APP_ROOT / "sessions"


def _path(session_id: str) -> Path:
    """返回会话文件路径，并确保目录存在。"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR / f"{session_id}.json"


def new_id() -> str:
    """生成会话 id：毫秒时间戳，保证唯一且可按时间排序（跨平台）。"""
    return str(int(time.time() * 1000))


def list_sessions() -> list[dict]:
    """按创建时间降序返回全部会话 [{id, title, messages}]，最新在最上，损坏文件跳过。"""
    if not SESSIONS_DIR.exists():
        return []
    out: list[dict] = []
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("跳过无法解析的会话文件: %s", p.name)
            continue
        msgs = data.get("messages")
        if not isinstance(msgs, list):
            msgs = []
        out.append(
            {
                "id": str(data.get("id") or p.stem),
                "title": str(data.get("title") or "新对话"),
                "messages": msgs,
            }
        )
    out.sort(key=lambda d: d["id"], reverse=True)
    return out


def save_session(session_id: str, title: str, messages: list) -> None:
    """写入单个会话；失败仅告警，不中断聊天。"""
    try:
        data = {
            "id": session_id,
            "title": title,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": [[r, t] for r, t in messages],
        }
        _path(session_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.warning("保存会话失败: %s", session_id)


def delete_session(session_id: str) -> None:
    """删除会话文件；不存在或失败仅告警。"""
    try:
        _path(session_id).unlink(missing_ok=True)
    except OSError:
        logger.warning("删除会话失败: %s", session_id)
