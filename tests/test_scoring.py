"""
评分系统单元测试
"""

import unittest
from scoring import (
    ScoringPipeline, CitationScorer, AuthorScorer,
    VenueScorer, FreshnessScorer, KeywordScorer,
)


class TestCitationScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = CitationScorer()

    def test_zero_citations(self):
        paper = {"s2_citation_count": 0, "s2_influential_citation_count": 0}
        self.assertEqual(self.scorer.score(paper), 0.0)

    def test_high_citations(self):
        paper = {"s2_citation_count": 100, "s2_influential_citation_count": 10}
        self.assertEqual(self.scorer.score(paper), 1.0)

    def test_medium_citations(self):
        paper = {"s2_citation_count": 20, "s2_influential_citation_count": 0}
        score = self.scorer.score(paper)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)


class TestAuthorScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = AuthorScorer()

    def test_known_affiliation(self):
        paper = {"s2_authors": [{"name": "Test", "affiliations": ["Google Research"]}]}
        self.assertEqual(self.scorer.score(paper), 1.0)

    def test_unknown_affiliation(self):
        paper = {"s2_authors": [{"name": "Test", "affiliations": ["Unknown Univ"]}]}
        self.assertEqual(self.scorer.score(paper), 0.0)

    def test_empty_authors(self):
        paper = {"s2_authors": []}
        self.assertEqual(self.scorer.score(paper), 0.0)


class TestVenueScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = VenueScorer()

    def test_top_venue(self):
        paper = {"s2_venue": "NeurIPS", "cr_published": True}
        score = self.scorer.score(paper)
        self.assertEqual(score, 1.0)

    def test_preprint(self):
        paper = {"s2_venue": "", "cr_published": False}
        self.assertEqual(self.scorer.score(paper), 0.0)

    def test_published_no_venue(self):
        paper = {"s2_venue": "", "cr_published": True}
        score = self.scorer.score(paper)
        self.assertGreater(score, 0.0)


class TestKeywordScorer(unittest.TestCase):
    def test_multiple_matches(self):
        scorer = KeywordScorer(keywords=["LLM", "reasoning", "agent"])
        paper = {"title": "LLM reasoning agent", "summary": "test"}
        self.assertEqual(scorer.score(paper), 1.0)

    def test_no_match(self):
        scorer = KeywordScorer(keywords=["quantum", "biology"])
        paper = {"title": "Transformer model", "summary": "attention"}
        self.assertEqual(scorer.score(paper), 0.0)


class TestFreshnessScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = FreshnessScorer()

    def test_missing_date(self):
        paper = {"published": ""}
        self.assertEqual(self.scorer.score(paper), 0.0)


class TestScoringPipeline(unittest.TestCase):
    def test_pipeline(self):
        pipeline = ScoringPipeline([
            CitationScorer(weight=50),
            KeywordScorer(keywords=["test"], weight=50),
        ])
        paper = {
            "s2_citation_count": 100,
            "s2_influential_citation_count": 10,
            "title": "A test paper",
            "summary": "test content",
        }
        score = pipeline.score_paper(paper)
        self.assertGreater(score, 0)
        self.assertIn("quality_score", paper)

    def test_rank_papers(self):
        pipeline = ScoringPipeline([CitationScorer(weight=100)])
        papers = [
            {"s2_citation_count": 5, "s2_influential_citation_count": 0},
            {"s2_citation_count": 100, "s2_influential_citation_count": 10},
            {"s2_citation_count": 0, "s2_influential_citation_count": 0},
        ]
        ranked = pipeline.rank_papers(papers)
        self.assertGreater(ranked[0]["quality_score"], ranked[1]["quality_score"])
        self.assertGreater(ranked[1]["quality_score"], ranked[2]["quality_score"])


if __name__ == "__main__":
    unittest.main()
