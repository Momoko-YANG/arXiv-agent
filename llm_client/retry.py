"""
智能重试 + 熔断器

重试策略按错误类型区分：
  - AuthError / BadRequest → 不重试，直接抛
  - RateLimit → 按 Retry-After 或递增等待
  - ServerError → 短间隔重试
  - ConnectionError → 长间隔重试

熔断器：连续失败 N 次后自动打开，冷却后自动半开测试
"""

import time

from .errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMRateLimitError,
    LLMServerError,
    LLMConnectionError,
    LLMCircuitOpenError,
)


class CircuitBreaker:
    """
    简易熔断器

    状态流转: CLOSED → OPEN → HALF_OPEN → CLOSED/OPEN
      - CLOSED: 正常，允许请求
      - OPEN: 熔断，快速失败
      - HALF_OPEN: 冷却后放一个请求试探
    """

    def __init__(self, failure_threshold: int = 4, cooldown: float = 60.0):
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._failures = 0
        self._last_failure_time = 0.0
        self._state = "CLOSED"  # CLOSED / OPEN / HALF_OPEN

    @property
    def state(self) -> str:
        if self._state == "OPEN":
            if time.time() - self._last_failure_time >= self.cooldown:
                self._state = "HALF_OPEN"
        return self._state

    def allow_request(self) -> bool:
        s = self.state
        return s in ("CLOSED", "HALF_OPEN")

    def record_success(self):
        self._failures = 0
        self._state = "CLOSED"

    def record_failure(self):
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self.failure_threshold:
            self._state = "OPEN"

    def reset(self):
        """手动重置（用于跨阶段重试）"""
        self._failures = 0
        self._state = "CLOSED"


def call_with_retry(fn, retries: int = 3, circuit: CircuitBreaker = None):
    """
    按错误类型智能重试

    Args:
        fn:       无参 callable，执行一次 LLM 请求
        retries:  最大重试次数（不含首次）
        circuit:  可选熔断器
    """
    # 熔断检查
    if circuit and not circuit.allow_request():
        raise LLMCircuitOpenError(
            f"熔断器打开（连续失败≥{circuit.failure_threshold}次），"
            f"冷却 {circuit.cooldown}s 后自动恢复"
        )

    last_err = None
    for attempt in range(retries + 1):
        try:
            result = fn()
            # 成功 → 重置熔断
            if circuit:
                circuit.record_success()
            return result

        except (LLMAuthError, LLMBadRequestError):
            # 不可重试，直接抛
            if circuit:
                circuit.record_failure()
            raise

        except LLMRateLimitError as e:
            last_err = e
            if attempt < retries:
                wait = 5 * (attempt + 1)  # 5s, 10s, 15s
                print(f"  ⏳ 限流，等待 {wait}s... ({e})")
                time.sleep(wait)
            else:
                if circuit:
                    circuit.record_failure()

        except LLMServerError as e:
            last_err = e
            if attempt < retries:
                wait = 2 * (attempt + 1)  # 2s, 4s, 6s
                print(f"  ⚠️  服务端错误，{wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                if circuit:
                    circuit.record_failure()

        except LLMConnectionError as e:
            last_err = e
            if attempt < retries:
                wait = 5 * (attempt + 1)  # 5s, 10s, 15s
                print(f"  ⚠️  连接失败，{wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                if circuit:
                    circuit.record_failure()

        except Exception as e:
            last_err = e
            if circuit:
                circuit.record_failure()
            if attempt < retries:
                wait = 3 * (attempt + 1)
                print(f"  ⚠️  未知错误，{wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                break

    raise last_err
