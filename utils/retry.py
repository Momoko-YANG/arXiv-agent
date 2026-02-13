"""
通用重试装饰器 — 指数退避
"""

import time
import functools


def retry(max_attempts: int = 3, delay_base: float = 2,
          exceptions: tuple = (Exception,)):
    """
    重试装饰器，支持指数退避

    Args:
        max_attempts: 最大尝试次数
        delay_base:   退避基数（秒），实际等待 = base^(attempt+1)
        exceptions:   需要捕获的异常类型
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt < max_attempts - 1:
                        wait = delay_base ** (attempt + 1)
                        print(f"  ⚠️  {func.__name__} 失败，{wait}s 后重试: {e}")
                        time.sleep(wait)
                    else:
                        raise
        return wrapper
    return decorator
