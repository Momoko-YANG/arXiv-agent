"""
arXiv Agent — 从 arXiv API 抓取最新论文
"""

import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import random
import time
from datetime import datetime, timedelta
from typing import List, Dict

from utils.text_clean import clean_title, clean_abstract


class ArxivAgent:
    """arXiv 论文抓取 Agent"""

    # 使用 https 端点（http 更易被限流 / 重定向）
    BASE_URL = "https://export.arxiv.org/api/query?"
    NS = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    def __init__(self, categories: List[str] = None):
        self.categories = categories or []

    def fetch_recent_papers(self, days: int = 1,
                            max_results: int = 200) -> List[Dict]:
        """
        抓取最近 N 天的论文

        注意：arXiv 每天约 UTC 20:00 更新，周末不更新。
              为避免时区 + 更新节奏导致漏抓，实际查询范围会额外 +1 天，
              并覆盖完整的 0000~2359 时间段。

        Returns:
            论文字典列表
        """
        # +1 天缓冲，防止时区 / 周末 / arXiv 延迟导致空结果
        actual_days = days + 1
        date_from = (datetime.now() - timedelta(days=actual_days)).strftime("%Y%m%d") + "0000"
        date_to = datetime.now().strftime("%Y%m%d") + "2359"

        if self.categories:
            cat_query = " OR ".join(f"cat:{c}" for c in self.categories)
            search_query = f"({cat_query}) AND submittedDate:[{date_from} TO {date_to}]"
        else:
            search_query = f"submittedDate:[{date_from} TO {date_to}]"

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        url = self.BASE_URL + urllib.parse.urlencode(params)

        print(f"  正在抓取 arXiv 论文...")
        print(f"  查询: {search_query[:80]}...")

        data = self._request_with_retry(url)
        if data is None:
            return []

        papers = self._parse_xml(data)
        print(f"  ✅ 成功抓取 {len(papers)} 篇论文")
        return papers

    def _request_with_retry(self, url: str,
                            max_retries: int = 6,
                            timeout: int = 60) -> bytes:
        """
        带指数退避的 arXiv 请求。

        - 429 / 5xx / 网络异常 / 超时统一走重试，共享同一个重试预算。
        - 退避时间指数增长并加入随机抖动；若响应带 Retry-After 头则优先遵从。
        - 全部失败返回 None。
        """
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "arXiv-Agent/1.0 (https://github.com/arXiv-Agent; daily feed)",
                    "Accept": "application/atom+xml",
                })
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()

            except urllib.error.HTTPError as e:
                # 429 限流、5xx 服务端错误可重试；其余直接失败
                retryable = e.code == 429 or 500 <= e.code < 600
                if not retryable or attempt >= max_retries - 1:
                    print(f"  ❌ arXiv 请求失败: HTTP {e.code} {e.reason}")
                    return None
                wait = self._retry_after(e) or self._backoff(attempt)
                tag = "429 限流" if e.code == 429 else f"HTTP {e.code}"
                print(f"  ⏳ arXiv {tag}，{wait:.0f}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait)

            except Exception as e:
                if attempt >= max_retries - 1:
                    print(f"  ❌ arXiv 请求失败: {e}")
                    return None
                wait = self._backoff(attempt)
                print(f"  ⚠️ 请求异常，{wait:.0f}s 后重试 ({attempt + 1}/{max_retries}): {e}")
                time.sleep(wait)

        return None

    @staticmethod
    def _backoff(attempt: int) -> float:
        """指数退避 + 抖动：~6, 12, 24, 48, 60(封顶)，再加 0~3s 抖动。"""
        return min(6 * (2 ** attempt), 60) + random.uniform(0, 3)

    @staticmethod
    def _retry_after(err: urllib.error.HTTPError) -> float:
        """读取 Retry-After 响应头（秒），无则返回 None。"""
        value = err.headers.get("Retry-After") if err.headers else None
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_xml(self, xml_data: bytes) -> List[Dict]:
        """解析 arXiv Atom XML"""
        root = ET.fromstring(xml_data)
        papers = []

        for entry in root.findall("atom:entry", self.NS):
            paper = {}

            paper["id"] = entry.find("atom:id", self.NS).text
            paper["arxiv_id"] = paper["id"].split("/abs/")[-1]
            paper["title"] = clean_title(entry.find("atom:title", self.NS).text)
            paper["summary"] = clean_abstract(entry.find("atom:summary", self.NS).text)

            paper["authors"] = [
                a.find("atom:name", self.NS).text
                for a in entry.findall("atom:author", self.NS)
            ]

            paper["published"] = entry.find("atom:published", self.NS).text

            paper["categories"] = [
                c.get("term") for c in entry.findall("atom:category", self.NS)
            ]

            for link in entry.findall("atom:link", self.NS):
                if link.get("title") == "pdf":
                    paper["pdf_url"] = link.get("href")

            papers.append(paper)

        return papers

    def format_paper(self, paper: Dict) -> str:
        """格式化单篇论文信息"""
        authors = ", ".join(paper["authors"][:3])
        if len(paper["authors"]) > 3:
            authors += "..."
        return (
            f"标题: {paper['title']}\n"
            f"ID: {paper['arxiv_id']} | 作者: {authors}\n"
            f"分类: {', '.join(paper['categories'])}\n"
            f"日期: {paper['published'][:10]}\n"
            f"PDF: {paper.get('pdf_url', 'N/A')}"
        )
