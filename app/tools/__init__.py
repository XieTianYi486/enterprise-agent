# ============================================================
# 工具装配：把各业务模块的工具注册进注册表
# ============================================================

from app.agent.registry import ToolRegistry
from app.tools import approval, expense, knowledge, leave

# 新增业务模块时只需在此追加
_MODULES = (leave, expense, approval, knowledge)


def build_registry() -> ToolRegistry:
    """构建包含全部业务工具的注册表。"""
    registry = ToolRegistry()
    for module in _MODULES:
        for tool in module.TOOLS:
            registry.register(tool)
    return registry