"""
OpenAI ChatCompletion 客户端 — 统一 LLM 调用入口
"""

import os
import time
import httpx


class OpenAIClient:
    """OpenAI ChatCompletion 客户端（带超时 + 重试 + 连通性检测）"""

    def __init__(self, api_key: str = None, model: str = None,
                 base_url: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("请设置 OPENAI_API_KEY 环境变量")

        self.default_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self._available = None  # None=未检测, True/False=已检测

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
        """检测 OpenAI API 是否可连通（首次调用时检测，缓存结果）"""
        if self._available is None:
            self._available = self._check_connectivity()
        return self._available

    def _check_connectivity(self) -> bool:
        """快速连通性检测（用最小请求试一次）"""
        try:
            self.client.models.list()
            print("  ✅ OpenAI API 连通")
            return True
        except Exception as e:
            print(f"  ⚠️  OpenAI API 不可达: {e}")
            print(f"  ⚠️  将跳过所有 LLM 步骤，使用降级模式")
            return False

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

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=model or self.default_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                # 成功后标记可用
                self._available = True
                return response.choices[0].message.content
            except Exception as e:
                if attempt < 2:
                    wait = 10 * (2 ** attempt)  # 10s, 20s
                    print(f"  ⚠️  OpenAI 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    # 标记不可用，后续调用可以提前跳过
                    self._available = False
                    raise
