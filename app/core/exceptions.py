# ============================================================
# 业务异常定义
# ============================================================


class AgentError(Exception):
    """所有 Agent 相关异常的基类。"""

    code = "AGENT_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LLMError(AgentError):
    """LLM 调用失败（网络、鉴权、限流、超时等）。"""

    code = "LLM_ERROR"


class ToolNotFoundError(AgentError):
    """模型请求了一个未注册的工具（幻觉函数名）。"""

    code = "TOOL_NOT_FOUND"


class ToolValidationError(AgentError):
    """工具参数校验失败（Pydantic 校验不通过）。"""

    code = "TOOL_VALIDATION_ERROR"


class ToolExecutionError(AgentError):
    """工具业务逻辑执行失败（余额不足、日期非法等）。"""

    code = "TOOL_EXECUTION_ERROR"


class AuthError(AgentError):
    """认证/授权失败。"""

    code = "AUTH_ERROR"