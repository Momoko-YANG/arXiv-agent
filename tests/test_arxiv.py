"""
arXiv Agent 单元测试（使用模拟数据，不调用外部 API）
"""

import unittest
from utils.database import ArxivDatabase
from summarizer.llm_summarizer import extract_key_sentences


class TestArxivDatabase(unittest.TestCase):
    """数据库 CRUD 测试"""

    def setUp(self):
        self.db = ArxivDatabase(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def _make_paper(self, arxiv_id="2402.00001"):
        return {
            "arxiv_id": arxiv_id,
            "title": "Test Paper Title",
            "summary": "This is a test abstract.",
            "published": "2024-02-15T00:00:00Z",
            "pdf_url": "https://arxiv.org/pdf/2402.00001",
            "authors": ["Alice", "Bob"],
            "categories": ["cs.AI", "cs.LG"],
        }

    def test_insert_and_query(self):
        paper = self._make_paper()
        self.assertTrue(self.db.insert_paper(paper))
        result = self.db.get_paper_by_arxiv_id("2402.00001")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Test Paper Title")

    def test_duplicate_insert(self):
        paper = self._make_paper()
        self.assertTrue(self.db.insert_paper(paper))
        self.assertFalse(self.db.insert_paper(paper))  # 重复

    def test_search(self):
        self.db.insert_paper(self._make_paper("2402.00001"))
        results = self.db.search_papers("Test Paper")
        self.assertEqual(len(results), 1)

    def test_stats(self):
        self.db.insert_paper(self._make_paper("2402.00001"))
        self.db.insert_paper(self._make_paper("2402.00002"))
        stats = self.db.get_stats()
        self.assertEqual(stats["total_papers"], 2)

    def test_enrichment_fields(self):
        paper = self._make_paper()
        paper["s2_citation_count"] = 42
        paper["cr_published"] = True
        paper["cr_journal"] = "NeurIPS"
        paper["quality_score"] = 75.5
        self.db.insert_paper(paper)
        result = self.db.get_paper_by_arxiv_id("2402.00001")
        self.assertEqual(result["citation_count"], 42)
        self.assertEqual(result["published_status"], 1)
        self.assertAlmostEqual(result["quality_score"], 75.5)


class TestKeysentenceExtraction(unittest.TestCase):
    """关键句抽取测试"""

    def test_short_abstract(self):
        abstract = "We propose a method. It works well."
        result = extract_key_sentences(abstract)
        self.assertEqual(result, abstract)  # 太短不截取

    def test_long_abstract(self):
        abstract = (
            "Current models struggle with complex tasks. "
            "Existing methods have limitations. "
            "We propose a novel framework for reasoning. "
            "Our approach leverages decomposition strategies. "
            "The method employs a verification module. "
            "Experiments demonstrate significant improvements. "
            "Results outperform state-of-the-art baselines. "
            "We also show strong generalization ability. "
            "Code is publicly available."
        )
        result = extract_key_sentences(abstract, max_sentences=4)
        # 应该抽取出包含关键词的句子
        self.assertIn("propose", result.lower())
        # 结果应该比原文短
        self.assertLess(len(result), len(abstract))


if __name__ == "__main__":
    unittest.main()
