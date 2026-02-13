"""
Semantic Scholar Agent — 补充引用量、作者机构、发表状态
使用 batch API 一次查完所有论文（比逐篇快 10x）
"""

import time
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

    def __init__(self, api_key: str = None, delay: float = 1.0):
        self.session = requests.Session()
        if api_key:
            self.session.headers["x-api-key"] = api_key
        self._limiter = RateLimiter(min_interval=delay)

    def _request(self, method: str, url: str, retries: int = 3,
                 **kwargs) -> Optional[requests.Response]:
        """通用请求方法（GET/POST 都用）"""
        kwargs.setdefault("timeout", 30)
        for attempt in range(retries):
            self._limiter.wait()
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 404:
                    return None
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 10))
                    print(f"    ⏳ S2 限流，等待 {wait}s...")
                    time.sleep(wait)
                    continue
                print(f"    ⚠️  S2 HTTP {resp.status_code}")
            except requests.RequestException as e:
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"    ⚠️  S2 失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    print(f"    ❌ S2 最终失败: {e}")
        return None

    # ------------------------------------------------------------------
    # 批量 API — 一次请求查完（核心加速）
    # ------------------------------------------------------------------

    def batch_get_papers(self, arxiv_ids: List[str]) -> Dict[str, dict]:
        """
        POST /paper/batch — 一次查完所有论文

        10 篇从 ~15s（逐篇） 降到 ~2s（一次请求）
        """
        if not arxiv_ids:
            return {}

        url = f"{self.BASE_URL}/paper/batch"
        ids = [f"ARXIV:{aid}" for aid in arxiv_ids]

        print(f"  📡 S2 批量查询 {len(ids)} 篇...")
        resp = self._request(
            "POST", url,
            json={"ids": ids},
            params={"fields": self.PAPER_FIELDS},
        )

        if not resp:
            print(f"    ⚠️  批量失败，回退逐篇查询")
            return self._fallback_sequential(arxiv_ids)

        data_list = resp.json()
        mapping = {}
        for arxiv_id, data in zip(arxiv_ids, data_list):
            if data:
                mapping[arxiv_id] = data

        print(f"  ✅ 命中 {len(mapping)}/{len(arxiv_ids)} 篇")
        return mapping

    def _fallback_sequential(self, arxiv_ids: List[str]) -> Dict[str, dict]:
        """批量失败时回退逐篇"""
        mapping = {}
        for aid in arxiv_ids:
            url = f"{self.BASE_URL}/paper/ARXIV:{aid}"
            resp = self._request("GET", url, params={"fields": self.PAPER_FIELDS})
            if resp:
                mapping[aid] = resp.json()
        return mapping

    # ------------------------------------------------------------------
    # 补充论文信息
    # ------------------------------------------------------------------

    def enrich_papers(self, papers: List[Dict]) -> List[Dict]:
        """批量补充 S2 信息（使用 batch API）"""
        arxiv_ids = [p["arxiv_id"] for p in papers if p.get("arxiv_id")]
        s2_data = self.batch_get_papers(arxiv_ids)

        for paper in papers:
            data = s2_data.get(paper.get("arxiv_id", ""))
            if data:
                paper["s2_citation_count"] = data.get("citationCount", 0) or 0
                paper["s2_influential_citation_count"] = (
                    data.get("influentialCitationCount", 0) or 0
                )
                paper["s2_venue"] = data.get("venue", "") or ""
                paper["s2_publication_types"] = data.get("publicationTypes") or []
                paper["s2_authors"] = [
                    {"name": a.get("name", ""),
                     "affiliations": a.get("affiliations") or []}
                    for a in (data.get("authors") or [])
                ]
            else:
                paper.setdefault("s2_citation_count", 0)
                paper.setdefault("s2_influential_citation_count", 0)
                paper.setdefault("s2_venue", "")
                paper.setdefault("s2_authors", [])
                paper.setdefault("s2_publication_types", [])

        return papers
