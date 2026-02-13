"""
统一日志配置
"""

import logging
import sys


def get_logger(name: str = "research_agent",
               level: int = logging.INFO) -> logging.Logger:
    """
    获取/创建 logger 实例

    Args:
        name:  logger 名称
        level: 日志级别
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(level)
    return logger
