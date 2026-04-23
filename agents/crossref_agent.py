"""
Crossref Agent — 查询论文正式发表状态

v3: 支持缓存 + ThreadPoolExecutor 并行查询
"""

import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

from utils.rate_limit import RateLimiter
from utils.cache import DiskCache


class CrossrefClient:
    """Crossref API 客户端"""

    BASE_URL = "https://api.crossref.org/works"

    def __init__(self, mailto: str = None, delay: float = 1.0,
                 cache: DiskCache = None):
        self._headers = {}
        if mailto:
            self._headers["User-Agent"] = f"arXiv-Agent/3.0 (mailto:{mailto})"
        self._session_local = threading.local()
        self._limiter = RateLimiter(min_interval=delay)
        self._cache = cache

    def _get_session(self) -> requests.Session:
        """每个线程独立 Session，避免并发共享连接状态。"""
        session = getattr(self._session_local, "session", None)
        if session is None:
            session = requests.Session()
            if self._headers:
                session.headers.update(self._headers)
            self._session_local.session = session
        return session

    def _get(self, params: dict, retries: int = 3) -> Optional[dict]:
        import time
        session = self._get_session()
        for attempt in range(retries):
            self._limiter.wait()
            try:
                resp = session.get(self.BASE_URL, params=params, timeout=30)
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
        """查询论文是否已正式发表（优先走缓存）"""
        result = {"published": False, "journal": "", "doi": "", "publisher": ""}

        # 缓存命中
        if self._cache:
            cache_key = DiskCache.make_key("crossref", title.lower().strip())
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

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

        # 写入缓存
        if self._cache:
            self._cache.set(cache_key, result)

        return result

    def enrich_papers(self, papers: List[Dict],
                      max_workers: int = 3) -> List[Dict]:
        """
        并行检查发表状态（ThreadPoolExecutor）

        v2 串行: 5 篇 ≈ 10s
        v3 并行: 5 篇 ≈ 4s（3 workers + rate limit）

        新增字段: cr_published, cr_journal, cr_doi, cr_publisher
        """
        total = len(papers)

        def _enrich_one(idx_paper):
            idx, paper = idx_paper
            title = paper.get("title", "")
            if not title:
                return idx, {}
            print(f"  📖 [{idx+1}/{total}] Crossref: {title[:50]}...")
            info = self.check_published(title)
            status = "✅ 已发表" if info["published"] else "⬜ 预印本"
            print(f"       {status} | {info['journal'] or '—'}")
            return idx, info

        # 并行查询
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_enrich_one, (i, p)): i
                for i, p in enumerate(papers)
            }
            for future in as_completed(futures):
                idx, info = future.result()
                if info:
                    papers[idx]["cr_published"] = info["published"]
                    papers[idx]["cr_journal"] = info["journal"]
                    papers[idx]["cr_doi"] = info["doi"]
                    papers[idx]["cr_publisher"] = info["publisher"]

        return papers
