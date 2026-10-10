# ============================================================
# 认证与安全：密码哈希（bcrypt）+ JWT 签发/校验
# ============================================================

import datetime as dt
from typing import Any, Dict

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import AuthError


def hash_password(plain: str) -> str:
    """明文密码 -> bcrypt 哈希。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码是否匹配哈希。"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, username: str) -> str:
    """签发 JWT。sub 为用户主键，Agent 侧据此注入工具上下文。"""
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """校验并解出 JWT 载荷。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthError("登录已过期，请重新登录")
    except jwt.PyJWTError:
        raise AuthError("无效的访问令牌")