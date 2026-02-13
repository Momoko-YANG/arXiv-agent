"""
OpenAI ChatCompletion 客户端 — 统一 LLM 调用入口
"""

import os
import time
import httpx


class OpenAIClient:
    """OpenAI ChatCompletion 客户端（带超时 + 重试）"""

    def __init__(self, api_key: str = None, model: str = None,
                 base_url: str = None):
        """
        Args:
            api_key:  OpenAI API Key，不传则读 OPENAI_API_KEY 环境变量
            model:    默认模型，不传则使用 gpt-4o-mini
            base_url: API 地址（可选，用于代理或兼容接口）
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "请设置 OPENAI_API_KEY 环境变量，或通过 api_key 参数传入"
            )

        self.default_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")

        try:
            from openai import OpenAI

            # 显式配置超时 + 内置重试，解决 GitHub Actions 网络不稳定
            http_client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=30.0,    # 连接超时 30s（默认 5s 太短）
                    read=120.0,      # 读取超时 120s（LLM 生成可能慢）
                    write=30.0,      # 写入超时 30s
                    pool=30.0,       # 连接池超时 30s
                ),
                transport=httpx.HTTPTransport(
                    retries=3,       # httpx 层自动重试 3 次（TCP 级别）
                ),
            )

            client_kwargs = {
                "api_key": self.api_key,
                "http_client": http_client,
                "max_retries": 3,    # OpenAI SDK 层重试 3 次（HTTP 级别）
            }
            if self.base_url:
                client_kwargs["base_url"] = self.base_url

            self.client = OpenAI(**client_kwargs)

        except ImportError:
            raise ImportError("请安装 openai 和 httpx 库: pip install openai httpx")

    def chat(self, prompt: str, system: str = None,
             model: str = None, temperature: float = 0.3,
             max_tokens: int = 2000) -> str:
        """
        发送 ChatCompletion 请求

        重试策略（三层防护）：
          1. httpx transport 层：TCP 连接失败自动重试 3 次
          2. OpenAI SDK 层：HTTP 错误（429/500/503）自动重试 3 次
          3. 应用层：以上都失败后，等 10s/20s/40s 再试 3 次
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
                return response.choices[0].message.content
            except Exception as e:
                if attempt < 2:
                    # 应用层重试用更长间隔（前两层已经重试过短间隔了）
                    wait = 10 * (2 ** attempt)  # 10s, 20s
                    print(f"  ⚠️  OpenAI 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    raise
