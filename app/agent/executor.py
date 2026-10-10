# ============================================================
# 工具执行器：把模型的 tool_call 变成「校验 -> 执行 -> 结构化结果」
#
# 三道防线：
#   1) 函数名白名单：不在注册表内直接拒绝（幻觉函数名）
#   2) JSON + Pydantic 双重校验：参数非法时把错误原因结构化回喂，
#      让模型自行修正，而不是抛 500 中断整轮对话
#   3) 业务异常收敛：任何未预期异常都转成 ok=false 的工具结果
# ============================================================

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import ValidationError

from app.agent.registry import Tool, ToolContext, ToolOutcome, ToolRegistry
from app.core.exceptions import AgentError, ToolExecutionError, ToolNotFoundError
from app.core.llm import ToolCall


@dataclass
class PreparedCall:
    """已通过校验、可直接执行的工具调用。"""

    tool: Tool
    tool_call_id: str
    args: Any  # 校验后的 Pydantic 模型实例
    args_dict: Dict[str, Any] = field(default_factory=dict)
    # 是否因「写操作需确认」而被挂起
    requires_confirmation: bool = False


@dataclass
class PrepareResult:
    """prepare 阶段的产物：要么可执行，要么带回结构化错误。"""

    ok: bool
    prepared: Optional[PreparedCall] = None
    tool_call_id: str = ""
    tool_name: str = ""
    error_content: Optional[str] = None
    error_display: Optional[Dict[str, Any]] = None


@dataclass
class ExecutionResult:
    """工具执行结果（回喂模型 + 前端展示）。"""

    tool_call_id: str
    tool_name: str
    ok: bool
    content: str
    display: Dict[str, Any] = field(default_factory=dict)


def _error_payload(error_type: str, message: str, **extra: Any) -> str:
    payload = {"ok": False, "error_type": error_type, "message": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


class ToolExecutor:
    """工具调用准备与执行。"""

    def __init__(self, registry: ToolRegistry, confirmation_enabled: bool = True) -> None:
        self.registry = registry
        self.confirmation_enabled = confirmation_enabled

    # ------------------------------------------------------------------
    # 阶段一：校验（不产生任何副作用）
    # ------------------------------------------------------------------
    def prepare(self, call: ToolCall, ctx: ToolContext) -> PrepareResult:
        # --- 防线 1：函数名白名单 ---
        try:
            tool = self.registry.get(call.name)
        except ToolNotFoundError:
            return PrepareResult(
                ok=False,
                tool_call_id=call.id,
                tool_name=call.name,
                error_content=_error_payload(
                    "unknown_tool",
                    f"函数 {call.name} 不存在。你只能调用以下工具之一，请改用最接近的那个。",
                    available_tools=self.registry.names(),
                ),
                error_display={"tool": call.name, "ok": False, "error_type": "unknown_tool"},
            )

        # --- 防线 2a：参数 JSON 解析 ---
        try:
            raw_args = call.parse_arguments()
        except (json.JSONDecodeError, TypeError) as exc:
            return PrepareResult(
                ok=False,
                tool_call_id=call.id,
                tool_name=call.name,
                error_content=_error_payload(
                    "invalid_json",
                    f"参数不是合法 JSON（{exc}）。请重新以严格 JSON 对象形式调用。",
                ),
                error_display={"tool": call.name, "ok": False, "error_type": "invalid_json"},
            )

        # --- 防线 2b：Pydantic 参数校验 ---
        try:
            args = tool.args_model.model_validate(raw_args)
        except ValidationError as exc:
            details = [
                {
                    "field": ".".join(str(p) for p in err["loc"]),
                    "problem": err["msg"],
                    "input": err.get("input"),
                }
                for err in exc.errors()
            ]
            return PrepareResult(
                ok=False,
                tool_call_id=call.id,
                tool_name=call.name,
                error_content=_error_payload(
                    "invalid_arguments", "参数校验未通过，请按 details 修正后重试。", details=details
                ),
                error_display={
                    "tool": call.name,
                    "ok": False,
                    "error_type": "invalid_arguments",
                    "details": details,
                },
            )

        # --- 防线 3：业务规则预检（在二次确认之前拦截，避免确认注定失败的操作）---
        if tool.precheck is not None:
            try:
                tool.precheck(ctx, args)
            except ToolExecutionError as exc:
                return PrepareResult(
                    ok=False,
                    tool_call_id=call.id,
                    tool_name=call.name,
                    error_content=_error_payload("business_error", exc.message),
                    error_display={
                        "tool": call.name,
                        "ok": False,
                        "error_type": "business_error",
                        "message": exc.message,
                    },
                )

        needs_confirm = bool(tool.requires_confirmation and self.confirmation_enabled)

        return PrepareResult(
            ok=True,
            prepared=PreparedCall(
                tool=tool,
                tool_call_id=call.id,
                args=args,
                args_dict=args.model_dump(),
                requires_confirmation=needs_confirm,
            ),
            tool_call_id=call.id,
            tool_name=call.name,
        )

    # ------------------------------------------------------------------
    # 阶段二：执行（可能产生副作用）
    # ------------------------------------------------------------------
    def execute(self, prepared: PreparedCall, ctx: ToolContext) -> ExecutionResult:
        try:
            outcome: ToolOutcome = prepared.tool.handler(ctx, prepared.args)
            return ExecutionResult(
                tool_call_id=prepared.tool_call_id,
                tool_name=prepared.tool.name,
                ok=outcome.ok,
                content=outcome.to_content(),
                display={"tool": prepared.tool.name, "ok": outcome.ok, "data": outcome.data},
            )
        except ToolExecutionError as exc:
            # 业务可预期错误：原样回喂，让模型向用户解释
            return ExecutionResult(
                tool_call_id=prepared.tool_call_id,
                tool_name=prepared.tool.name,
                ok=False,
                content=_error_payload("business_error", exc.message),
                display={"tool": prepared.tool.name, "ok": False, "error_type": "business_error",
                         "message": exc.message},
            )
        except AgentError as exc:
            return ExecutionResult(
                tool_call_id=prepared.tool_call_id,
                tool_name=prepared.tool.name,
                ok=False,
                content=_error_payload("agent_error", exc.message),
                display={"tool": prepared.tool.name, "ok": False, "message": exc.message},
            )
        except Exception as exc:  # noqa: BLE001 - 兜底，绝不让异常穿透打断对话
            return ExecutionResult(
                tool_call_id=prepared.tool_call_id,
                tool_name=prepared.tool.name,
                ok=False,
                content=_error_payload("internal_error", f"工具内部错误: {exc}"),
                display={"tool": prepared.tool.name, "ok": False, "error_type": "internal_error"},
            )

    @staticmethod
    def rejected_result(tool_call_id: str, tool_name: str) -> ExecutionResult:
        """用户拒绝执行写操作时，回喂给模型的工具结果。"""
        return ExecutionResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            ok=False,
            content=_error_payload(
                "user_rejected",
                "用户已明确拒绝执行该写操作。不要再次调用它，改为向用户确认是否需要调整内容。",
            ),
            display={"tool": tool_name, "ok": False, "error_type": "user_rejected"},
        )