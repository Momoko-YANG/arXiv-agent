"""
作者/机构评分器
"""

from typing import Dict
from .base_score import BaseScorer

# 知名研究机构（可扩展）
KNOWN_AFFILIATIONS = {
    # 企业
    "google", "deepmind", "openai", "meta", "microsoft",
    "apple", "nvidia", "amazon", "bytedance", "tencent",
    "alibaba", "baidu", "anthropic", "mistral",
    # 高校
    "stanford", "mit", "berkeley", "cmu", "harvard",
    "oxford", "cambridge", "tsinghua", "peking", "princeton",
    "eth zurich", "mila", "inria", "caltech", "columbia",
    "university of washington", "cornell",
}


class AuthorScorer(BaseScorer):
    """
    作者机构评分

    检查 Semantic Scholar 返回的作者机构信息，
    命中知名机构则加分。
    """

    name = "author"

    def __init__(self, weight: float = 20,
                 known_affiliations: set = None):
        super().__init__(weight)
        self.known = known_affiliations or KNOWN_AFFILIATIONS

    def score(self, paper: Dict) -> float:
        affiliations_text = ""
        for author in paper.get("s2_authors", []):
            for aff in author.get("affiliations", []):
                affiliations_text += " " + aff.lower()

        if not affiliations_text:
            return 0.0

        # 命中一个就给满分（机构间不叠加）
        for org in self.known:
            if org in affiliations_text:
                return 1.0

        return 0.0
