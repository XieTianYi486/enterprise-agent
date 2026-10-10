# ============================================================
# 应用配置：从 .env / 环境变量加载（pydantic-settings）
# ============================================================

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（Enterprise-Agent/）
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """全局配置。所有字段均可被 .env 同名变量覆盖。"""

    # ==================== 应用基础 ====================
    APP_NAME: str = "企业办公 Agent"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8002

    # ==================== 数据库 ====================
    DATABASE_URL: str = f"sqlite:///{(BASE_DIR / 'data' / 'agent.db').as_posix()}"

    # ==================== 阿里云百炼 ====================
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_OPENAI_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen-plus"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 2048

    # ==================== Agent 护栏 ====================
    # 单轮对话最多允许的「LLM 决策 + 工具执行」循环次数，防止无限循环
    AGENT_MAX_TURNS: int = 8
    # 单轮对话总耗时上限（秒）
    AGENT_TIMEOUT_SECONDS: float = 60.0
    # 写操作是否强制人工二次确认
    WRITE_CONFIRMATION_ENABLED: bool = True
    # 送入 LLM 的历史消息条数上限（防止上下文膨胀）
    MAX_HISTORY_MESSAGES: int = 30

    # ==================== 认证 ====================
    AUTH_ENABLED: bool = True
    JWT_SECRET_KEY: str = "dev-only-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # ==================== 演示账号 ====================
    DEMO_USERNAME: str = "demo"
    DEMO_PASSWORD: str = "demo123456"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()