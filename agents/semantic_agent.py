"""
Semantic Scholar Agent — 补充引用量、作者机构、发表状态
"""

import requests
from typing import List, Dict, Optional

from utils.rate_limit import RateLimiter


class SemanticScholarClient:
    """Semantic Scholar API 客户端"""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    PAPER_FIELDS = ",".join([
        "title", "citationCount", "influentialCitationCount",
        "venue", "year", "authors", "authors.affiliations",
        "publicationTypes", "externalIds",
    ])

    def __init__(self, api_key: str = None, delay: float = 1.5):
        self.session = requests.Session()
        if api_key:
            self.session.headers["x-api-key"] = api_key
        self._limiter = RateLimiter(min_interval=delay)

    def _get(self, url: str, params: dict = None,
             retries: int = 3) -> Optional[dict]:
        """带重试 + 速率限制的 GET"""
        import time
        for attempt in range(retries):
            self._limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    return None
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 30))
                    print(f"    ⏳ S2 限流，等待 {wait}s...")
                    time.sleep(wait)
                    continue
                print(f"    ⚠️  S2 HTTP {resp.status_code}")
            except requests.RequestException as e:
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"    ⚠️  S2 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    print(f"    ❌ S2 请求最终失败: {e}")
        return None

    def get_paper(self, arxiv_id: str) -> Optional[Dict]:
        """根据 arXiv ID 查询 Semantic Scholar"""
        url = f"{self.BASE_URL}/paper/ARXIV:{arxiv_id}"
        return self._get(url, {"fields": self.PAPER_FIELDS})

    def enrich_papers(self, papers: List[Dict]) -> List[Dict]:
        """
        批量补充 Semantic Scholar 信息

        新增字段: s2_citation_count, s2_influential_citation_count,
                  s2_venue, s2_authors, s2_publication_types
        """
        total = len(papers)
        for idx, paper in enumerate(papers):
            arxiv_id = paper.get("arxiv_id", "")
            if not arxiv_id:
                continue

            print(f"  📡 [{idx+1}/{total}] S2: {arxiv_id}")
            data = self.get_paper(arxiv_id)

            if data:
                paper["s2_citation_count"] = data.get("citationCount", 0) or 0
                paper["s2_influential_citation_count"] = (
                    data.get("influentialCitationCount", 0) or 0
                )
                paper["s2_venue"] = data.get("venue", "") or ""
                paper["s2_publication_types"] = data.get("publicationTypes") or []
                paper["s2_authors"] = [
                    {
                        "name": a.get("name", ""),
                        "affiliations": a.get("affiliations") or [],
                    }
                    for a in (data.get("authors") or [])
                ]
                print(f"       ✅ 引用={paper['s2_citation_count']}, "
                      f"会议={paper['s2_venue'] or '—'}")
            else:
                paper.setdefault("s2_citation_count", 0)
                paper.setdefault("s2_influential_citation_count", 0)
                paper.setdefault("s2_venue", "")
                paper.setdefault("s2_authors", [])
                paper.setdefault("s2_publication_types", [])
                print(f"       ⚪ 未找到")

        return papers
