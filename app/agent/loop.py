# ============================================================
# ReAct 主循环
#
# 一轮对话的完整流程：
#   用户输入 -> [LLM 决策] -> 有 tool_calls ?
#       ├─ 否 -> 输出最终回答，结束
#       └─ 是 -> 校验参数 -> 是否需要人工确认
#               ├─ 是 -> 挂起，返回 awaiting_confirmation
#               └─ 否 -> 执行工具 -> 结果回喂 -> 回到 LLM 决策
#
# 内置护栏：
#   1) max_turns   —— 限制决策轮数，防止模型空转
#   2) 总超时       —— 整轮对话墙钟上限
#   3) 函数名白名单 —— 见 executor.prepare
#   4) 参数校验     —— 见 executor.prepare
#   5) 写操作确认   —— 任一批次含写操作则整批挂起
#   6) 历史裁剪     —— 只保留最近 N 条，防止上下文膨胀
# ============================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.agent.executor import PreparedCall, ToolExecutor
from app.agent.prompts import build_system_prompt
from app.agent.registry import ToolContext, ToolRegistry
from app.agent.state import Conversation, PendingAction
from app.core.config import settings
from app.core.exceptions import AgentError
from app.core.llm import LLMClient

EventCallback = Optional[Callable[[Dict[str, Any]], Awaitable[None]]]


@dataclass
class AgentRunResult:
    """一轮 Agent 运行的结果。"""

    # completed | awaiting_confirmation | max_turns | timeout
    status: str
    answer: str = ""
    pending: Optional[PendingAction] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    usage: Dict[str, int] = field(default_factory=dict)


class AgentLoop:
    """ReAct 循环执行器。"""

    def __init__(self, llm: LLMClient, registry: ToolRegistry, executor: ToolExecutor) -> None:
        self.llm = llm
        self.registry = registry
        self.executor = executor

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    async def run(
        self,
        conv: Conversation,
        user_text: str,
        ctx: ToolContext,
        on_event: EventCallback = None,
    ) -> AgentRunResult:
        """处理一条新的用户消息。"""
        if conv.pending is not None:
            raise AgentError("上一笔操作还在等待确认，请先确认或取消")
        conv.messages.append({"role": "user", "content": user_text})
        return await self._drive(conv, ctx, on_event)

    async def resume(
        self,
        conv: Conversation,
        approved: bool,
        ctx: ToolContext,
        on_event: EventCallback = None,
    ) -> AgentRunResult:
        """用户对待确认操作给出答复后，继续推进对话。"""
        pending = conv.pending
        if pending is None:
            raise AgentError("当前会话没有等待确认的操作")

        conv.pending = None
        await self._emit(
            on_event,
            {"type": "confirmation_result", "data": {"action_id": pending.action_id, "approved": approved}},
        )

        # 统一在这里补执行（只读调用也在其中），保证工具结果条数
        # 与 assistant 消息里的 tool_calls 一一对应
        for prepared in pending.calls:
            result = (
                self.executor.execute(prepared, ctx)
                if approved
                else ToolExecutor.rejected_result(prepared.tool_call_id, prepared.tool.name)
            )
            self._append_tool_message(conv, result.tool_call_id, result.content)
            await self._emit(on_event, {"type": "tool_result", "data": result.display})

        return await self._drive(conv, ctx, on_event)

    # ------------------------------------------------------------------
    # 核心循环
    # ------------------------------------------------------------------
    async def _drive(
        self,
        conv: Conversation,
        ctx: ToolContext,
        on_event: EventCallback,
    ) -> AgentRunResult:
        steps: List[Dict[str, Any]] = []
        usage_total: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        deadline = time.monotonic() + settings.AGENT_TIMEOUT_SECONDS
        tools = self.registry.schemas()

        async def on_token(token: str) -> None:
            await self._emit(on_event, {"type": "token", "data": token})

        for turn in range(1, settings.AGENT_MAX_TURNS + 1):
            # --- 护栏：总超时 ---
            if time.monotonic() > deadline:
                await self._emit(on_event, {"type": "error", "data": {"message": "处理超时"}})
                return AgentRunResult(
                    status="timeout",
                    answer="抱歉，这次请求处理时间过长已中止，建议把需求拆成更小的步骤。",
                    steps=steps,
                    turns=turn - 1,
                    usage=usage_total,
                )

            # --- LLM 决策 ---
            response = await self.llm.chat(
                self._build_messages(conv, ctx),
                tools=tools,
                on_token=on_token,
            )
            for key, value in response.usage.items():
                usage_total[key] = usage_total.get(key, 0) + value

            # --- 分支 A：无工具调用 -> 最终回答 ---
            if not response.tool_calls:
                conv.messages.append(response.to_assistant_message())
                conv.updated_at = time.time()
                answer = response.content.strip() or "（本次没有生成回答，请换个说法再试一次）"
                await self._emit(on_event, {"type": "final", "data": {"answer": answer}})
                return AgentRunResult(
                    status="completed",
                    answer=answer,
                    steps=steps,
                    turns=turn,
                    usage=usage_total,
                )

            # --- 分支 B：有工具调用 ---
            conv.messages.append(response.to_assistant_message())
            if response.content and response.content.strip():
                # 部分模型会先输出一段思考文本再发起调用
                await self._emit(on_event, {"type": "thought", "data": {"text": response.content.strip()}})

            prepared_all: List[PreparedCall] = []
            for call in response.tool_calls:
                await self._emit(
                    on_event,
                    {"type": "tool_call", "data": {"tool": call.name, "args": call.arguments}},
                )
                prep = self.executor.prepare(call, ctx)

                if not prep.ok:
                    # 校验失败：把结构化错误作为工具结果回喂，让模型自我修正
                    self._append_tool_message(conv, prep.tool_call_id, prep.error_content or "")
                    await self._emit(on_event, {"type": "tool_result", "data": prep.error_display or {}})
                    steps.append({"turn": turn, "tool": call.name, "ok": False, "stage": "validate"})
                    continue

                prepared_all.append(prep.prepared)
                steps.append(
                    {
                        "turn": turn,
                        "tool": call.name,
                        "ok": True,
                        "stage": "validate",
                        "needs_confirmation": prep.prepared.requires_confirmation,
                    }
                )

            # --- 护栏：写操作挂起等待确认 ---
            confirm_calls = [p for p in prepared_all if p.requires_confirmation]
            if confirm_calls:
                pending = PendingAction(
                    action_id=f"act_{int(time.time() * 1000)}_{len(confirm_calls)}",
                    calls=prepared_all,
                    summary=self._build_summary(confirm_calls),
                )
                conv.pending = pending
                conv.updated_at = time.time()
                await self._emit(on_event, {"type": "awaiting_confirmation", "data": pending.to_public()})
                return AgentRunResult(
                    status="awaiting_confirmation",
                    pending=pending,
                    steps=steps,
                    turns=turn,
                    usage=usage_total,
                )

            # --- 只读批次：直接执行 ---
            for prepared in prepared_all:
                result = self.executor.execute(prepared, ctx)
                self._append_tool_message(conv, result.tool_call_id, result.content)
                await self._emit(on_event, {"type": "tool_result", "data": result.display})
                steps.append({"turn": turn, "tool": prepared.tool.name, "ok": result.ok, "stage": "execute"})

        # --- 护栏：达到最大步数 ---
        conv.updated_at = time.time()
        await self._emit(on_event, {"type": "error", "data": {"message": "达到最大步数限制"}})
        return AgentRunResult(
            status="max_turns",
            answer="抱歉，本次任务需要的步骤过多，已被安全策略中止。请把需求拆得更具体一些再试。",
            steps=steps,
            turns=settings.AGENT_MAX_TURNS,
            usage=usage_total,
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _build_messages(self, conv: Conversation, ctx: ToolContext) -> List[Dict[str, Any]]:
        """系统提示 + 裁剪后的历史。"""
        system = {
            "role": "system",
            "content": build_system_prompt(ctx.user_name, ctx.dept_name, ctx.manager_name),
        }
        history = conv.messages[-settings.MAX_HISTORY_MESSAGES:]
        # 裁剪后不能以孤立的 tool 消息开头（缺少对应的 assistant tool_calls）
        while history and history[0].get("role") == "tool":
            history = history[1:]
        return [system] + history

    @staticmethod
    def _append_tool_message(conv: Conversation, tool_call_id: str, content: str) -> None:
        conv.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content or "{}"}
        )

    @staticmethod
    def _build_summary(confirm_calls: List[PreparedCall]) -> str:
        return "；".join(p.tool.describe_args(p.args) for p in confirm_calls)

    @staticmethod
    async def _emit(on_event: EventCallback, event: Dict[str, Any]) -> None:
        if on_event is not None:
            await on_event(event)