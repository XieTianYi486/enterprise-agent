# ============================================================
# 接口层请求/响应模型
# ============================================================

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------- 认证 ----------------
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class UserInfo(BaseModel):
    id: int
    username: str
    name: str
    dept_name: str
    position: str
    manager_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


# ---------------- 对话 ----------------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户输入")
    conversation_id: Optional[str] = Field(None, description="会话 ID；不传则新建会话")


class ConfirmRequest(BaseModel):
    conversation_id: str = Field(..., description="会话 ID")
    action_id: str = Field(..., description="待确认动作 ID")
    approved: bool = Field(..., description="true=同意执行，false=拒绝")


class PendingCallInfo(BaseModel):
    tool: str
    args: Dict[str, Any] = {}
    requires_confirmation: bool = False


class PendingActionInfo(BaseModel):
    action_id: str
    summary: str
    calls: List[PendingCallInfo] = []


class ChatResponse(BaseModel):
    conversation_id: str
    # completed | awaiting_confirmation | max_turns | timeout
    status: str
    answer: str = ""
    pending: Optional[PendingActionInfo] = None
    steps: List[Dict[str, Any]] = []
    turns: int = 0
    usage: Dict[str, int] = {}


class ChatHistoryResponse(BaseModel):
    conversation_id: str
    messages: List[Dict[str, Any]]
    has_pending: bool