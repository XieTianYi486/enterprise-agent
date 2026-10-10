# ============================================================
# 数据库连接与会话管理
# 默认 SQLite（零配置）；生产可改为 MySQL/PostgreSQL
# ============================================================

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import BASE_DIR, settings

# SQLite 需要预先创建数据目录
(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)

# SQLite 在多线程下需关闭同线程检查（FastAPI 线程池）
_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（幂等）。"""
    from app.db import models  # noqa: F401  确保模型已注册到 Base.metadata

    Base.metadata.create_all(bind=engine)