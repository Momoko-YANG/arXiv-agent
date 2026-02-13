"""
HTTP 直连 Transport — 唯一网络通道

不依赖 OpenAI SDK，纯 requests 实现。
稳定、可控、header 干净。
"""

import os
import requests

from .errors import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMAuthError,
    LLMServerError,
    LLMBadRequestError,
)


class OpenAIHTTPTransport:
    """OpenAI-compatible HTTP 直连传输层"""

    def __init__(self, api_key: str = None, base_url: str = None,
                 timeout: int = 90):
        self.api_key = self._sanitize(
            api_key or os.getenv("OPENAI_API_KEY", "")
        )
        if not self.api_key:
            raise ValueError("请设置 OPENAI_API_KEY 环境变量")

        raw_url = base_url or os.getenv("OPENAI_BASE_URL", "")
        self.base_url = raw_url.strip().rstrip("/") if raw_url.strip() else "https://api.openai.com/v1"
        self.timeout = timeout

        # 持久 session，复用连接池
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    @staticmethod
    def _sanitize(raw: str) -> str:
        """清洗 key：去空白 + 拦截非法字符"""
        key = (raw or "").strip()
        if any(ch in key for ch in ("\r", "\n", "\t")):
            raise ValueError(
                "OPENAI_API_KEY 包含非法换行/制表符，请在 Secrets 中重新粘贴"
            )
        return key

    def call(self, messages: list, model: str = "gpt-4o-mini",
             temperature: float = 0.3, max_tokens: int = 2000) -> str:
        """
        发送一次 ChatCompletion 请求

        成功 → 返回 content 字符串
        失败 → 抛出对应的 LLM*Error（由上层决定是否重试）
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            resp = self._session.post(url, json=payload, timeout=self.timeout)
        except requests.ConnectionError as e:
            raise LLMConnectionError(f"连接失败: {e}") from e
        except requests.Timeout as e:
            raise LLMConnectionError(f"请求超时({self.timeout}s): {e}") from e
        except requests.RequestException as e:
            raise LLMConnectionError(f"网络异常: {e}") from e

        # 按 HTTP 状态码分类
        status = resp.status_code

        if status == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]

        # 提取 API 错误信息
        try:
            err_body = resp.json()
            err_msg = err_body.get("error", {}).get("message", resp.text[:300])
        except Exception:
            err_msg = resp.text[:300]

        detail = f"HTTP {status}: {err_msg}"

        if status == 401 or status == 403:
            raise LLMAuthError(detail)
        elif status == 429:
            raise LLMRateLimitError(detail)
        elif status == 400:
            raise LLMBadRequestError(detail)
        elif status >= 500:
            raise LLMServerError(detail)
        else:
            raise LLMServerError(detail)
