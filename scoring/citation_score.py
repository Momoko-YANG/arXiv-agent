"""
引用量评分器
"""

from typing import Dict
from .base_score import BaseScorer


class CitationScorer(BaseScorer):
    """
    引用数 + 有影响力引用 综合评分

    权重分配：引用数占 70%，有影响力引用占 30%
    """

    name = "citation"

    def __init__(self, weight: float = 30):
        super().__init__(weight)

    def score(self, paper: Dict) -> float:
        # ---- 引用数 (0 ~ 0.7) ----
        citations = paper.get("s2_citation_count", 0)
        if citations >= 100:
            cite_score = 0.7
        elif citations >= 50:
            cite_score = 0.6
        elif citations >= 20:
            cite_score = 0.5
        elif citations >= 10:
            cite_score = 0.4
        elif citations >= 5:
            cite_score = 0.25
        elif citations >= 1:
            cite_score = 0.1
        else:
            cite_score = 0.0

        # ---- 有影响力引用 (0 ~ 0.3) ----
        influential = paper.get("s2_influential_citation_count", 0)
        if influential >= 10:
            inf_score = 0.3
        elif influential >= 5:
            inf_score = 0.2
        elif influential >= 1:
            inf_score = 0.1
        else:
            inf_score = 0.0

        return min(cite_score + inf_score, 1.0)
