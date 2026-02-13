"""
OpenAI ChatCompletion 客户端 — 统一 LLM 调用入口
"""

import os
import time


class OpenAIClient:
    """OpenAI ChatCompletion 客户端（带重试）"""

    def __init__(self, api_key: str = None, model: str = None):
        """
        Args:
            api_key: OpenAI API Key，不传则读 OPENAI_API_KEY 环境变量
            model:   默认模型，不传则使用 gpt-4o-mini
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "请设置 OPENAI_API_KEY 环境变量，或通过 api_key 参数传入"
            )

        self.default_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
        except ImportError:
            raise ImportError("请安装 openai 库: pip install openai")

    def chat(self, prompt: str, system: str = None,
             model: str = None, temperature: float = 0.3,
             max_tokens: int = 2000) -> str:
        """
        发送 ChatCompletion 请求（带重试）

        Args:
            prompt:      用户消息
            system:      系统提示词（可选）
            model:       覆盖默认模型（可选）
            temperature: 温度参数
            max_tokens:  最大 token 数
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
                    wait = 2 ** (attempt + 1)
                    print(f"  ⚠️  OpenAI 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    raise
