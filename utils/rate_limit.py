"""
通用速率限制器
"""

import time


class RateLimiter:
    """简单速率限制器 — 保证两次调用之间的最小间隔"""

    def __init__(self, min_interval: float = 1.0):
        """
        Args:
            min_interval: 两次调用之间的最小间隔（秒）
        """
        self.min_interval = min_interval
        self._last_call = 0.0

    def wait(self):
        """在调用前执行，自动等待到满足间隔"""
        elapsed = time.time() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.time()

    def __enter__(self):
        self.wait()
        return self

    def __exit__(self, *args):
        pass
