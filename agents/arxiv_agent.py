"""
arXiv Agent — 从 arXiv API 抓取最新论文
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict

from utils.text_clean import clean_title, clean_abstract


class ArxivAgent:
    """arXiv 论文抓取 Agent"""

    BASE_URL = "http://export.arxiv.org/api/query?"
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

        Returns:
            论文字典列表
        """
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        date_to = datetime.now().strftime("%Y%m%d")

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

        try:
            with urllib.request.urlopen(url) as resp:
                data = resp.read()
        except Exception as e:
            print(f"  ❌ arXiv 请求失败: {e}")
            return []

        papers = self._parse_xml(data)
        print(f"  ✅ 成功抓取 {len(papers)} 篇论文")
        return papers

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
