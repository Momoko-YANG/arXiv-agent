"""
LLM 错误分类 — 不同错误类型，不同重试策略
"""


class LLMError(Exception):
    """LLM 调用基类异常"""
    pass


class LLMConnectionError(LLMError):
    """网络连接失败（DNS / TCP / TLS）→ 可重试，长间隔"""
    pass


class LLMRateLimitError(LLMError):
    """429 限流 → 可重试，按 Retry-After 等"""
    pass


class LLMAuthError(LLMError):
    """401/403 认证失败 → 不可重试，直接抛出"""
    pass


class LLMServerError(LLMError):
    """500/502/503 服务端错误 → 可重试，短间隔"""
    pass


class LLMBadRequestError(LLMError):
    """400 请求格式错误（prompt 太长等）→ 不可重试"""
    pass


class LLMCircuitOpenError(LLMError):
    """熔断器打开 → 快速失败，不发请求"""
    pass
