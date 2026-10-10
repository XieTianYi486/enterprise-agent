# ============================================================
# 认证接口：登录换取 JWT、查看当前用户
# ============================================================

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import LoginRequest, TokenResponse, UserInfo
from app.core.config import settings
from app.core.exceptions import AuthError
from app.core.security import create_access_token, verify_password
from app.db.database import get_db
from app.db.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


def _to_user_info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        name=user.name,
        dept_name=user.dept_name,
        position=user.position,
        manager_name=user.manager_name,
    )


@router.post("/login", response_model=TokenResponse, summary="登录获取访问令牌")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    # 统一提示，避免暴露「用户名是否存在」
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthError("用户名或密码错误")

    token = create_access_token(user.id, user.username)
    return TokenResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
        user=_to_user_info(user),
    )


@router.get("/me", response_model=UserInfo, summary="获取当前登录用户")
def me(user: User = Depends(get_current_user)) -> UserInfo:
    return _to_user_info(user)