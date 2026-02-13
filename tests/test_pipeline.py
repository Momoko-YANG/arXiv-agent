"""
端到端流水线测试（使用模拟数据）
"""

import unittest
from scoring import ScoringPipeline, CitationScorer, AuthorScorer, VenueScorer, KeywordScorer
from summarizer.llm_summarizer import extract_key_sentences


class TestEndToEnd(unittest.TestCase):
    """端到端评分流水线测试"""

    def _make_papers(self):
        """创建模拟论文数据"""
        return [
            {
                "arxiv_id": "2402.00001",
                "title": "Large Language Model Reasoning with Chain-of-Thought",
                "summary": "We propose a new method to improve LLM reasoning...",
                "published": "2024-02-15",
                "authors": ["Alice"],
                "categories": ["cs.AI"],
                "s2_citation_count": 50,
                "s2_influential_citation_count": 5,
                "s2_venue": "NeurIPS",
                "s2_authors": [{"name": "Alice", "affiliations": ["Google"]}],
                "cr_published": True,
                "cr_journal": "NeurIPS 2024",
            },
            {
                "arxiv_id": "2402.00002",
                "title": "A Study on Image Classification",
                "summary": "We study basic image classification techniques...",
                "published": "2024-02-14",
                "authors": ["Bob"],
                "categories": ["cs.CV"],
                "s2_citation_count": 0,
                "s2_influential_citation_count": 0,
                "s2_venue": "",
                "s2_authors": [{"name": "Bob", "affiliations": []}],
                "cr_published": False,
                "cr_journal": "",
            },
            {
                "arxiv_id": "2402.00003",
                "title": "Efficient Transformer Quantization for Edge Devices",
                "summary": "We present an efficient quantization method...",
                "published": "2024-02-15",
                "authors": ["Charlie"],
                "categories": ["cs.LG"],
                "s2_citation_count": 10,
                "s2_influential_citation_count": 1,
                "s2_venue": "ICML",
                "s2_authors": [{"name": "Charlie", "affiliations": ["MIT"]}],
                "cr_published": True,
                "cr_journal": "ICML 2024",
            },
        ]

    def test_scoring_ranking(self):
        """高质量论文应该排在前面"""
        pipeline = ScoringPipeline([
            CitationScorer(weight=30),
            AuthorScorer(weight=20),
            VenueScorer(weight=20),
            KeywordScorer(keywords=["LLM", "reasoning", "transformer"], weight=15),
        ])
        papers = self._make_papers()
        ranked = pipeline.rank_papers(papers)

        # 第一篇（NeurIPS + Google + 50 citations + LLM）应该排第一
        self.assertEqual(ranked[0]["arxiv_id"], "2402.00001")
        # 最差的（0 citations + no venue + no affiliation）应该排最后
        self.assertEqual(ranked[-1]["arxiv_id"], "2402.00002")

    def test_scoring_values(self):
        """评分应在 0-100 范围内"""
        pipeline = ScoringPipeline([
            CitationScorer(weight=50),
            VenueScorer(weight=50),
        ])
        papers = self._make_papers()
        for p in papers:
            score = pipeline.score_paper(p)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_key_extraction_integration(self):
        """关键句抽取应对所有论文都能工作"""
        papers = self._make_papers()
        for p in papers:
            result = extract_key_sentences(p["summary"])
            self.assertTrue(len(result) > 0)


if __name__ == "__main__":
    unittest.main()
