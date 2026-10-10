# ============================================================
# 会话状态：保存多轮对话上下文与「待确认」的写操作
#
# 为什么需要它：
#   Agent 是多轮交互的，写操作要挂起等用户确认，
#   因此必须把 messages 与 pending 状态保存在服务端。
# ============================================================

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agent.executor import PreparedCall
from app.core.exceptions import AuthError


@dataclass
class PendingAction:
    """一批等待用户确认的调用（含只读调用，确认后一起补执行）。"""

    action_id: str
    calls: List[PreparedCall]
    summary: str
    created_at: float = field(default_factory=time.time)

    def to_public(self) -> Dict[str, Any]:
        """对外暴露的结构（不含 Python 对象，可直接 JSON 序列化）。"""
        return {
            "action_id": self.action_id,
            "summary": self.summary,
            "calls": [
                {
                    "tool": c.tool.name,
                    "args": c.args_dict,
                    "requires_confirmation": c.requires_confirmation,
                }
                for c in self.calls
            ],
        }


@dataclass
class Conversation:
    """一个会话的全部状态。"""

    id: str
    user_id: int
    messages: List[Dict[str, Any]] = field(default_factory=list)
    pending: Optional[PendingAction] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ConversationStore:
    """
    进程内会话存储。

    生产环境应替换为 Redis（多实例共享 + TTL 自动过期），
    此处保持零外部依赖，clone 下来即可运行。
    """

    def __init__(self, ttl_seconds: int = 3600, max_conversations: int = 500) -> None:
        self._data: Dict[str, Conversation] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_conversations

    def get_or_create(self, conversation_id: Optional[str], user_id: int) -> Conversation:
        with self._lock:
            self._evict_locked()
            if conversation_id and conversation_id in self._data:
                conv = self._data[conversation_id]
                if conv.user_id != user_id:
                    raise AuthError("无权访问该会话")
                return conv

            conv = Conversation(id=conversation_id or uuid.uuid4().hex, user_id=user_id)
            self._data[conv.id] = conv
            return conv

    def get(self, conversation_id: str) -> Optional[Conversation]:
        with self._lock:
            return self._data.get(conversation_id)

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            self._data.pop(conversation_id, None)

    def _evict_locked(self) -> None:
        now = time.time()
        expired = [k for k, v in self._data.items() if now - v.updated_at > self._ttl]
        for k in expired:
            self._data.pop(k, None)

        if len(self._data) >= self._max:
            # 超量时淘汰最久未活跃的会话
            oldest = sorted(self._data.items(), key=lambda kv: kv[1].updated_at)
            for k, _ in oldest[: max(1, len(oldest) // 10)]:
                self._data.pop(k, None)


# 全局单例
conversation_store = ConversationStore()