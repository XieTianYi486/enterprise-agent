# ============================================================
# 工具注册表
#
# 设计要点：
#   1) 工具的入参用 Pydantic 模型声明，JSON Schema 自动生成，
#      模型看到的 schema 与运行时校验用的是同一份定义，不会漂移。
#   2) 注册表是「唯一事实来源」：模型请求的函数名必须先在这里命中，
#      否则判为幻觉调用直接拒绝（护栏一：函数名白名单）。
# ============================================================

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

from app.core.exceptions import ToolNotFoundError


@dataclass
class ToolContext:
    """
    工具执行上下文。

    由服务端根据登录态注入，模型不可见、不可篡改 ——
    这是「模型不能冒充他人查数据」的关键设计。
    """

    user_id: int
    user_name: str
    dept_name: str
    manager_name: str
    db: Any  # sqlalchemy.orm.Session


@dataclass
class ToolOutcome:
    """工具的业务返回。data 会被序列化后回喂给模型。"""

    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)

    def to_content(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, default=str)


Handler = Callable[[ToolContext, BaseModel], ToolOutcome]
Summarizer = Callable[[BaseModel], str]
PreCheck = Callable[[ToolContext, BaseModel], None]


def _clean_schema(node: Any) -> Any:
    """去掉 Pydantic 生成的 title 字段，保持 schema 精简（省 token）。"""
    if isinstance(node, dict):
        return {k: _clean_schema(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_clean_schema(v) for v in node]
    return node


@dataclass
class Tool:
    """一个可被模型调用的工具。"""

    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Handler
    # 是否会产生副作用（写库）
    is_write: bool = False
    # 是否需要用户二次确认后才真正执行
    requires_confirmation: bool = False
    # 二次确认前的业务规则预检（只读、无副作用）；不通过抛 ToolExecutionError，
    # 在弹确认框之前就拦截，避免让用户确认一个注定失败的操作
    precheck: Optional[PreCheck] = None
    # 生成给用户看的确认文案，例如「提交年假 3 天（10-10 至 10-12）」
    summarize: Optional[Summarizer] = None

    def openai_schema(self) -> Dict[str, Any]:
        """导出为 OpenAI Function Calling 的 tools 结构。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _clean_schema(self.args_model.model_json_schema()),
            },
        }

    def describe_args(self, args: BaseModel) -> str:
        if self.summarize is not None:
            return self.summarize(args)
        return json.dumps(args.model_dump(), ensure_ascii=False)


class ToolRegistry:
    """工具注册表。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """按名取工具，未注册则抛 ToolNotFoundError（护栏一）。"""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"未注册的工具: {name}")
        return tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def all(self) -> List[Tool]:
        return list(self._tools.values())

    def schemas(self) -> List[Dict[str, Any]]:
        """全部工具的 JSON Schema，供模型决策。"""
        return [t.openai_schema() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)