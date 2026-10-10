# ============================================================
# LLM 客户端：阿里云百炼 OpenAI 兼容接口
# 支持 Function Calling（工具调用）与流式 token 增量推送
#
# 设计要点：
#   1) 统一走 stream=True，内部累积 content 与 tool_calls。
#      非流式场景忽略 on_token 即可，避免维护两套解析逻辑。
#   2) tool_calls 在流式响应中按 index 分片下发，必须按 index 聚合。
# ============================================================

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.exceptions import LLMError

TokenCallback = Optional[Callable[[str], Awaitable[None]]]


@dataclass
class ToolCall:
    """模型请求的一次工具调用。"""

    id: str
    name: str
    arguments: str = ""  # 原始 JSON 字符串（可能为非法 JSON，交由执行器校验）

    def parse_arguments(self) -> Dict[str, Any]:
        """把原始参数字符串解析为 dict。空串按空对象处理。"""
        if not self.arguments or not self.arguments.strip():
            return {}
        return json.loads(self.arguments)

    def to_message_dict(self) -> Dict[str, Any]:
        """转成 OpenAI 消息协议中的 tool_call 结构，用于回写历史。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments or "{}"},
        }


@dataclass
class LLMResponse:
    """一次 LLM 调用的结果。"""

    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)

    def to_assistant_message(self) -> Dict[str, Any]:
        """转成可回写 messages 的 assistant 消息。"""
        msg: Dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [tc.to_message_dict() for tc in self.tool_calls]
        return msg


class LLMClient:
    """百炼大模型客户端（异步）。"""

    def __init__(self) -> None:
        if not settings.DASHSCOPE_API_KEY:
            raise LLMError("未配置 DASHSCOPE_API_KEY，请在 .env 中填写")
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        self._client = AsyncOpenAI(
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_OPENAI_BASE_URL,
        )

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        on_token: TokenCallback = None,
    ) -> LLMResponse:
        """
        发起一次对话，返回文本与工具调用请求。

        参数:
            messages:   OpenAI 协议消息列表
            tools:      工具的 JSON Schema 列表（None 表示禁用工具）
            tool_choice: auto | none | required
            on_token:   文本增量回调（传入即实现逐字流式）
        """
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        content_parts: List[str] = []
        # index -> {id, name, arguments}，流式下 tool_call 按 index 分片
        tool_acc: Dict[int, Dict[str, str]] = {}
        usage: Dict[str, int] = {}

        try:
            stream = await self._client.chat.completions.create(**kwargs)

            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                if delta.content:
                    content_parts.append(delta.content)
                    if on_token is not None:
                        await on_token(delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if tc.index is not None else 0
                        slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function:
                            # 函数名由服务端一次性下发，直接覆盖；
                            # 参数则按分片累加拼接
                            if tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function.arguments:
                                slot["arguments"] += tc.function.arguments

        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一收敛为 LLMError
            raise LLMError(f"LLM 调用失败: {exc}") from exc

        tool_calls = [
            ToolCall(id=s["id"] or f"call_{i}", name=s["name"], arguments=s["arguments"])
            for i, s in sorted(tool_acc.items())
        ]

        return LLMResponse(content="".join(content_parts), tool_calls=tool_calls, usage=usage)


# --- 全局单例 ---
_client: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    """获取 LLM 客户端单例。"""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client