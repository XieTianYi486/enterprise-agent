# ============================================================
# 对话接口：普通对话 / SSE 流式对话 / 写操作确认 / 会话管理
# ============================================================

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent.loop import AgentLoop, AgentRunResult
from app.agent.registry import ToolContext
from app.agent.runtime import get_agent_loop
from app.agent.state import Conversation, conversation_store
from app.api.deps import build_tool_context, get_current_user
from app.api.schemas import (
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
)
from app.core.exceptions import AgentError, AuthError
from app.db.database import SessionLocal, get_db
from app.db.models import User

router = APIRouter(prefix="/api/v1", tags=["对话"])


def _serialize(result: AgentRunResult, conversation_id: str) -> Dict[str, Any]:
    """把运行结果转成接口响应结构。"""
    return {
        "conversation_id": conversation_id,
        "status": result.status,
        "answer": result.answer,
        "pending": result.pending.to_public() if result.pending else None,
        "steps": result.steps,
        "turns": result.turns,
        "usage": result.usage,
    }


def _load_conversation(conversation_id: str, user: User) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if conv is None:
        raise AgentError("会话不存在或已过期，请重新发起对话")
    if conv.user_id != user.id:
        raise AuthError("无权访问该会话")
    return conv


# ----------------------------------------------------------------------
# 非流式对话
# ----------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse, summary="与办公 Agent 对话（非流式）")
async def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    conversation = conversation_store.get_or_create(payload.conversation_id, user.id)
    ctx = build_tool_context(user, db)
    result = await get_agent_loop().run(conversation, payload.message, ctx)
    return ChatResponse(**_serialize(result, conversation.id))


# ----------------------------------------------------------------------
# SSE 流式对话
# ----------------------------------------------------------------------
async def _drive_and_report(
    loop: AgentLoop,
    conversation: Conversation,
    message: str,
    ctx: ToolContext,
    queue: "asyncio.Queue[Dict[str, Any] | None]",
) -> None:
    """在后台任务里跑 Agent 循环，把事件推入队列。"""

    async def on_event(event: Dict[str, Any]) -> None:
        await queue.put(event)

    try:
        result = await loop.run(conversation, message, ctx, on_event)
        await queue.put({"type": "result", "data": _serialize(result, conversation.id)})
    except AgentError as exc:
        await queue.put({"type": "error", "data": {"message": exc.message}})
    except Exception as exc:  # noqa: BLE001
        await queue.put({"type": "error", "data": {"message": f"服务内部错误: {exc}"}})
    finally:
        await queue.put(None)  # 结束哨兵


@router.post("/chat/stream", summary="与办公 Agent 对话（SSE 流式）")
async def chat_stream(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    conversation = conversation_store.get_or_create(payload.conversation_id, user.id)
    loop = get_agent_loop()

    # 用户信息先取出来，避免在流式过程中持有已关闭的请求级 Session
    user_snapshot = (user.id, user.name, user.dept_name, user.manager_name)

    async def event_generator() -> AsyncGenerator[str, None]:
        queue: "asyncio.Queue[Dict[str, Any] | None]" = asyncio.Queue()
        db = SessionLocal()  # 独立会话，生命周期由本生成器掌控
        try:
            ctx = ToolContext(
                user_id=user_snapshot[0],
                user_name=user_snapshot[1],
                dept_name=user_snapshot[2],
                manager_name=user_snapshot[3],
                db=db,
            )
            task = asyncio.create_task(
                _drive_and_report(loop, conversation, payload.message, ctx, queue)
            )
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            await task
        finally:
            db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证逐条推送
        },
    )


# ----------------------------------------------------------------------
# 写操作确认
# ----------------------------------------------------------------------
@router.post("/chat/confirm", response_model=ChatResponse, summary="确认/拒绝待执行的写操作")
async def confirm(
    payload: ConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    conversation = _load_conversation(payload.conversation_id, user)
    pending = conversation.pending
    if pending is None:
        raise AgentError("当前会话没有等待确认的操作")
    if pending.action_id != payload.action_id:
        raise AgentError("待确认的操作已失效，请重新发起本次申请")

    ctx = build_tool_context(user, db)
    result = await get_agent_loop().resume(conversation, payload.approved, ctx)
    return ChatResponse(**_serialize(result, conversation.id))


# ----------------------------------------------------------------------
# 会话管理
# ----------------------------------------------------------------------
@router.get("/chat/{conversation_id}", response_model=ChatHistoryResponse, summary="查看会话历史")
def get_history(
    conversation_id: str,
    user: User = Depends(get_current_user),
) -> ChatHistoryResponse:
    conversation = _load_conversation(conversation_id, user)
    return ChatHistoryResponse(
        conversation_id=conversation.id,
        messages=conversation.messages,
        has_pending=conversation.pending is not None,
    )


@router.delete("/chat/{conversation_id}", summary="清空会话")
def reset_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
) -> Dict[str, str]:
    _load_conversation(conversation_id, user)
    conversation_store.delete(conversation_id)
    return {"status": "ok", "message": "会话已清空"}


# ----------------------------------------------------------------------
# 工具清单（调试/演示用：查看模型能看到哪些工具）
# ----------------------------------------------------------------------
@router.get("/tools", summary="查看当前注册的工具清单")
def list_tools(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    registry = get_agent_loop().registry
    return {
        "count": len(registry),
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "is_write": tool.is_write,
                "requires_confirmation": tool.requires_confirmation,
                "parameters": tool.openai_schema()["function"]["parameters"],
            }
            for tool in registry.all()
        ],
    }