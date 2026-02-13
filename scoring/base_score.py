"""
评分系统 — 基类 + 评分流水线 + 通用评分器
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class BaseScorer(ABC):
    """评分器基类"""

    name: str = "base"
    weight: float = 1.0  # 该评分器的最大贡献分

    def __init__(self, weight: float = None):
        if weight is not None:
            self.weight = weight

    @abstractmethod
    def score(self, paper: Dict) -> float:
        """
        计算归一化分数 (0.0 ~ 1.0)

        Args:
            paper: 论文字典
        Returns:
            0.0 ~ 1.0 的浮点数
        """
        ...


class ScoringPipeline:
    """评分流水线 — 组合多个评分器，生成综合质量分"""

    def __init__(self, scorers: List[BaseScorer] = None):
        self.scorers = scorers or []

    def score_paper(self, paper: Dict) -> float:
        """
        计算单篇论文的综合质量分 (0 ~ 100)

        公式: quality_score = sum(scorer.score * scorer.weight)
               归一化到 0-100
        """
        total_weight = sum(s.weight for s in self.scorers) or 1
        weighted_sum = sum(s.score(paper) * s.weight for s in self.scorers)
        score = round(weighted_sum / total_weight * 100, 1)
        paper["quality_score"] = score
        return score

    def rank_papers(self, papers: List[Dict]) -> List[Dict]:
        """评分并按分数降序排列"""
        for p in papers:
            self.score_paper(p)
        papers.sort(key=lambda p: p.get("quality_score", 0), reverse=True)
        return papers


# ---------------------------------------------------------------------------
# 通用评分器（不单独开文件的小型评分器放在这里）
# ---------------------------------------------------------------------------

# 顶会/顶刊关键词
TOP_VENUES = {
    # ML / AI
    "neurips", "nips", "icml", "iclr", "aaai", "ijcai",
    # CV
    "cvpr", "iccv", "eccv",
    # NLP
    "acl", "emnlp", "naacl", "coling",
    # 数据挖掘
    "kdd", "www", "sigir", "wsdm",
    # 期刊
    "nature", "science", "jmlr", "pami", "tpami",
    "transactions on neural networks",
}


class VenueScorer(BaseScorer):
    """顶会/顶刊 + 正式发表状态评分"""

    name = "venue"

    def __init__(self, weight: float = 20):
        super().__init__(weight)

    def score(self, paper: Dict) -> float:
        s = 0.0

        # 顶会/顶刊 (0 or 0.6)
        venue = paper.get("s2_venue", "").lower()
        if venue:
            for top in TOP_VENUES:
                if top in venue:
                    s += 0.6
                    break

        # 正式发表 (0 or 0.4)
        if paper.get("cr_published"):
            s += 0.4

        return min(s, 1.0)


class KeywordScorer(BaseScorer):
    """关键词匹配评分"""

    name = "keyword"

    def __init__(self, keywords: List[str] = None, weight: float = 15):
        super().__init__(weight)
        self.keywords = keywords or []

    def score(self, paper: Dict) -> float:
        if not self.keywords:
            return 0.0

        text = (paper.get("title", "") + " " + paper.get("summary", "")).lower()
        matched = sum(1 for kw in self.keywords if kw.lower() in text)

        if matched >= 3:
            return 1.0
        elif matched >= 2:
            return 0.67
        elif matched >= 1:
            return 0.33
        return 0.0
