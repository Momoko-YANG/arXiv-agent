"""
Crossref Agent — 查询论文正式发表状态
"""

import requests
from typing import List, Dict, Optional

from utils.rate_limit import RateLimiter


class CrossrefClient:
    """Crossref API 客户端"""

    BASE_URL = "https://api.crossref.org/works"

    def __init__(self, mailto: str = None, delay: float = 1.0):
        self.session = requests.Session()
        if mailto:
            self.session.headers["User-Agent"] = (
                f"arXiv-Agent/2.0 (mailto:{mailto})"
            )
        self._limiter = RateLimiter(min_interval=delay)

    def _get(self, params: dict, retries: int = 3) -> Optional[dict]:
        import time
        for attempt in range(retries):
            self._limiter.wait()
            try:
                resp = self.session.get(self.BASE_URL, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    print(f"    ⏳ Crossref 限流，等待 5s...")
                    time.sleep(5)
                    continue
            except requests.RequestException as e:
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"    ⚠️  Crossref 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    print(f"    ❌ Crossref 最终失败: {e}")
        return None

    def check_published(self, title: str) -> Dict:
        """查询论文是否已正式发表"""
        result = {"published": False, "journal": "", "doi": "", "publisher": ""}

        data = self._get({"query.title": title, "rows": 1})
        if not data:
            return result

        items = data.get("message", {}).get("items", [])
        if not items:
            return result

        item = items[0]

        # 标题粗略匹配
        cr_title = " ".join(item.get("title", [])).lower()
        query_lower = title.lower()
        short = min(len(cr_title), len(query_lower), 50)
        if short > 10:
            if query_lower[:short] not in cr_title and cr_title[:short] not in query_lower:
                return result

        container = item.get("container-title", [])
        result["published"] = bool(container)
        result["journal"] = container[0] if container else ""
        result["doi"] = item.get("DOI", "")
        result["publisher"] = item.get("publisher", "")
        return result

    def enrich_papers(self, papers: List[Dict]) -> List[Dict]:
        """
        批量检查发表状态

        新增字段: cr_published, cr_journal, cr_doi, cr_publisher
        """
        total = len(papers)
        for idx, paper in enumerate(papers):
            title = paper.get("title", "")
            if not title:
                continue

            print(f"  📖 [{idx+1}/{total}] Crossref: {title[:50]}...")
            info = self.check_published(title)

            paper["cr_published"] = info["published"]
            paper["cr_journal"] = info["journal"]
            paper["cr_doi"] = info["doi"]
            paper["cr_publisher"] = info["publisher"]

            status = "✅ 已发表" if info["published"] else "⬜ 预印本"
            print(f"       {status} | {info['journal'] or '—'}")

        return papers
