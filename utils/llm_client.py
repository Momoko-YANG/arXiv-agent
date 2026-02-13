"""
OpenAI ChatCompletion 客户端 — 统一 LLM 调用入口
"""

import os
import time
import httpx


class OpenAIClient:
    """OpenAI ChatCompletion 客户端（带超时 + 重试 + 临时熔断）"""

    def __init__(self, api_key: str = None, model: str = None,
                 base_url: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("请设置 OPENAI_API_KEY 环境变量")

        self.default_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        # 熔断窗口：连续失败后，短时间内快速失败，避免每次都等待 10s/20s
        self._disabled_until = 0.0
        self._last_error = ""

        try:
            from openai import OpenAI

            http_client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=30.0,
                    read=120.0,
                    write=30.0,
                    pool=30.0,
                ),
                transport=httpx.HTTPTransport(retries=3),
                follow_redirects=True,
            )

            client_kwargs = {
                "api_key": self.api_key,
                "http_client": http_client,
                "max_retries": 2,
            }
            if self.base_url:
                client_kwargs["base_url"] = self.base_url

            self.client = OpenAI(**client_kwargs)

        except ImportError:
            raise ImportError("pip install openai httpx")

    @property
    def available(self) -> bool:
        """是否允许发起 LLM 请求（不做网络预检测）"""
        return time.time() >= self._disabled_until

    def reset_circuit(self):
        """重置熔断状态，允许再次尝试连接 LLM"""
        self._disabled_until = 0.0

    def chat(self, prompt: str, system: str = None,
             model: str = None, temperature: float = 0.3,
             max_tokens: int = 2000) -> str:
        """
        发送 ChatCompletion 请求

        重试策略：
          1. httpx transport 层：TCP 级别重试 3 次
          2. OpenAI SDK 层：HTTP 429/500/503 重试 2 次
          3. 应用层：10s / 20s 再试 2 次
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # 熔断窗口内快速失败，避免重复等待
        if time.time() < self._disabled_until:
            raise RuntimeError(
                f"OpenAI 暂时不可用（熔断中）: {self._last_error or 'connection error'}"
            )

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=model or self.default_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                # 成功后清空熔断状态
                self._disabled_until = 0.0
                self._last_error = ""
                return response.choices[0].message.content
            except Exception as e:
                if attempt < 2:
                    wait = 10 * (2 ** attempt)  # 10s, 20s
                    print(f"  ⚠️  OpenAI 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    # 连续失败后短暂熔断 120s，避免后续调用重复卡住
                    self._last_error = str(e)
                    self._disabled_until = time.time() + 120
                    print("  ⚠️  OpenAI 连续失败，进入 120s 熔断窗口")
                    raise
