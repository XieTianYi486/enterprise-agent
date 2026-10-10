# ============================================================
# 应用入口
# ============================================================

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import auth, chat
from app.core.config import settings
from app.core.exceptions import AgentError, AuthError
from app.db.database import SessionLocal, init_db
from app.db.seed import seed_demo_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("enterprise-agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时建表、写入演示数据并预热 Agent。"""
    init_db()

    db = SessionLocal()
    try:
        seed_demo_data(db)
    finally:
        db.close()
    logger.info("数据库就绪，演示账号：%s / %s", settings.DEMO_USERNAME, settings.DEMO_PASSWORD)

    if not settings.DASHSCOPE_API_KEY:
        logger.warning("未配置 DASHSCOPE_API_KEY —— 对话接口将不可用，请在 .env 中填写后重启")
    else:
        try:
            from app.agent.runtime import get_agent_loop

            agent_loop = get_agent_loop()
            logger.info(
                "Agent 已就绪，注册工具 %d 个：%s",
                len(agent_loop.registry),
                "、".join(agent_loop.registry.names()),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Agent 初始化失败：%s", exc)

    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="基于 Function Calling 的企业办公智能体：工具编排、参数校验、写操作确认与全链路护栏。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AgentError)
async def agent_error_handler(request: Request, exc: AgentError) -> JSONResponse:
    """业务异常统一返回结构化错误，避免暴露堆栈。"""
    status_code = 401 if isinstance(exc, AuthError) else 400
    return JSONResponse(
        status_code=status_code,
        content={"code": exc.code, "message": exc.message},
    )


app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health", tags=["系统"], summary="健康检查")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "model": settings.LLM_MODEL,
        "auth_enabled": settings.AUTH_ENABLED,
    }


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False, summary="极简聊天页")
def index() -> FileResponse:
    """返回单文件聊天页，便于本地直接可视化体验 Agent 能力。"""
    return FileResponse(_STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)