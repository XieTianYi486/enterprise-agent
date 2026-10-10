# ============================================================
# Agent 运行时装配：LLM + 工具注册表 + 执行器 -> AgentLoop 单例
# ============================================================

from typing import Optional

from app.agent.executor import ToolExecutor
from app.agent.loop import AgentLoop
from app.core.config import settings
from app.core.llm import get_llm
from app.tools import build_registry

_loop: Optional[AgentLoop] = None


def get_agent_loop() -> AgentLoop:
    """获取全局唯一的 AgentLoop（内部持有 LLM 客户端与工具注册表）。"""
    global _loop
    if _loop is None:
        registry = build_registry()
        executor = ToolExecutor(
            registry,
            confirmation_enabled=settings.WRITE_CONFIRMATION_ENABLED,
        )
        _loop = AgentLoop(get_llm(), registry, executor)
    return _loop