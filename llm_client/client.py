"""
LLMClient — 唯一对外接口

所有模块只调用:
    llm.generate(prompt)
    llm.generate(prompt, system=..., temperature=...)

不关心 SDK/HTTP、重试、熔断、限流。
"""

import os

from .transport import OpenAIHTTPTransport
from .retry import call_with_retry, CircuitBreaker
from .errors import LLMCircuitOpenError


class LLMClient:
    """
    工业级 LLM 客户端

    特性:
      - 纯 HTTP 直连（无 SDK 依赖）
      - 错误分类 + 智能重试
      - 自动熔断 + 冷却恢复
      - API Key 自动清洗
    """

    def __init__(self, api_key: str = None, model: str = None,
                 base_url: str = None, timeout: int = 90,
                 max_retries: int = 3):
        self.default_model = (
            model
            or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        ).strip()

        self.max_retries = max_retries

        # 传输层
        self._transport = OpenAIHTTPTransport(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

        # 熔断器（连续 4 次失败 → 熔断 60s）
        self._circuit = CircuitBreaker(failure_threshold=4, cooldown=60.0)

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def generate(self, prompt: str, system: str = None,
                 model: str = None, temperature: float = 0.3,
                 max_tokens: int = 2000) -> str:
        """
        发送 LLM 请求（带智能重试 + 熔断）

        Args:
            prompt:      用户 prompt
            system:      system message（可选）
            model:       模型名（默认用初始化时的）
            temperature: 温度
            max_tokens:  最大 token 数

        Returns:
            LLM 生成的文本

        Raises:
            LLMAuthError:         key 无效（不会重试）
            LLMBadRequestError:   请求格式错误（不会重试）
            LLMCircuitOpenError:  熔断器打开
            其他 LLMError:         重试耗尽后抛出
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        use_model = model or self.default_model

        return call_with_retry(
            fn=lambda: self._transport.call(
                messages=messages,
                model=use_model,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            retries=self.max_retries,
            circuit=self._circuit,
        )

    # ------------------------------------------------------------------
    # 兼容旧接口（平滑迁移）
    # ------------------------------------------------------------------

    def chat(self, prompt: str, system: str = None,
             model: str = None, temperature: float = 0.3,
             max_tokens: int = 2000) -> str:
        """兼容旧 OpenAIClient.chat() 签名"""
        return self.generate(
            prompt=prompt, system=system,
            model=model, temperature=temperature,
            max_tokens=max_tokens,
        )

    # ------------------------------------------------------------------
    # 熔断控制
    # ------------------------------------------------------------------

    def reset_circuit(self):
        """重置熔断器（跨阶段重试时调用）"""
        self._circuit.reset()

    @property
    def available(self) -> bool:
        """当前是否允许发起 LLM 请求"""
        return self._circuit.allow_request()

    @property
    def circuit_state(self) -> str:
        """熔断器状态: CLOSED / OPEN / HALF_OPEN"""
        return self._circuit.state
