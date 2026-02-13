"""
新鲜度评分器
"""

from datetime import datetime, timedelta
from typing import Dict
from .base_score import BaseScorer


class FreshnessScorer(BaseScorer):
    """
    论文新鲜度评分

    越新的论文分越高（鼓励关注最新成果）
    """

    name = "freshness"

    def __init__(self, weight: float = 15, decay_days: int = 30):
        """
        Args:
            weight:     权重
            decay_days: 超过多少天视为「不新鲜」（分数降为 0）
        """
        super().__init__(weight)
        self.decay_days = decay_days

    def score(self, paper: Dict) -> float:
        published = paper.get("published", "")
        if not published:
            return 0.0

        try:
            pub_date = datetime.strptime(published[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return 0.0

        age_days = (datetime.now() - pub_date).days

        if age_days <= 1:
            return 1.0     # 今天/昨天
        elif age_days <= 3:
            return 0.8     # 3 天内
        elif age_days <= 7:
            return 0.6     # 一周内
        elif age_days <= 14:
            return 0.4     # 两周内
        elif age_days <= self.decay_days:
            return 0.2     # 一个月内
        else:
            return 0.0
