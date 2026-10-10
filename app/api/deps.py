# ============================================================
# FastAPI 依赖：登录态解析与工具上下文构造
# ============================================================

from typing import Optional

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.agent.registry import ToolContext
from app.core.config import settings
from app.core.exceptions import AuthError
from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.models import User


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """
    解析 Authorization: Bearer <token> 得到当前用户。

    AUTH_ENABLED=false 时（本地调试）直接返回演示账号，
    免去每次都要先登录换 token 的麻烦。
    """
    if not settings.AUTH_ENABLED:
        user = db.query(User).filter(User.username == settings.DEMO_USERNAME).first()
        if user is None:
            raise AuthError("演示账号未初始化，请先重启服务以写入种子数据")
        return user

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("缺少访问令牌，请在请求头携带 Authorization: Bearer <token>")

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)

    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise AuthError("令牌载荷异常")

    user = db.get(User, user_id)
    if user is None:
        raise AuthError("用户不存在或已被禁用")
    return user


def build_tool_context(user: User, db: Session) -> ToolContext:
    """
    构造工具执行上下文。

    注意：user_id 只来自登录态，模型无法通过参数指定他人，
    这是防止越权读取他人数据的关键。
    """
    return ToolContext(
        user_id=user.id,
        user_name=user.name,
        dept_name=user.dept_name,
        manager_name=user.manager_name,
        db=db,
    )