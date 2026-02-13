"""
llm_client — 工业级 LLM 调用入口

用法:
    from llm_client import LLMClient

    llm = LLMClient()
    result = llm.generate("你好")
"""

from .client import LLMClient
from .errors import (
    LLMError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMAuthError,
    LLMServerError,
    LLMBadRequestError,
    LLMCircuitOpenError,
)

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMConnectionError",
    "LLMRateLimitError",
    "LLMAuthError",
    "LLMServerError",
    "LLMBadRequestError",
    "LLMCircuitOpenError",
]
