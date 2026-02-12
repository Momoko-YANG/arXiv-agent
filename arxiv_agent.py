#!/usr/bin/env python3
"""
arXiv Daily Paper Scraper Agent
抓取 arXiv 每日更新的论文
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict
import json
import time


class ArxivAgent:
    """arXiv 论文抓取 Agent"""
    
    def __init__(self, categories: List[str] = None):
        """
        初始化 Agent
        
        Args:
            categories: 关注的分类，例如 ['cs.AI', 'cs.LG', 'cs.CV']
                       如果为 None，则抓取所有分类
        """
        self.base_url = 'http://export.arxiv.org/api/query?'
        self.categories = categories or []
        self.namespace = {'atom': 'http://www.w3.org/2005/Atom',
                         'arxiv': 'http://arxiv.org/schemas/atom'}
    
    def fetch_recent_papers(self, days: int = 1, max_results: int = 100) -> List[Dict]:
        """
        抓取最近几天的论文
        
        Args:
            days: 抓取最近几天的论文
            max_results: 最大返回数量
            
        Returns:
            论文列表，每个论文是一个字典
        """
        # 构建搜索查询
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        date_to = datetime.now().strftime('%Y%m%d')
        
        # 如果指定了分类，构建分类查询
        if self.categories:
            cat_query = ' OR '.join([f'cat:{cat}' for cat in self.categories])
            search_query = f'({cat_query}) AND submittedDate:[{date_from} TO {date_to}]'
        else:
            search_query = f'submittedDate:[{date_from} TO {date_to}]'
        
        # 构建完整 URL
        params = {
            'search_query': search_query,
            'start': 0,
            'max_results': max_results,
            'sortBy': 'submittedDate',
            'sortOrder': 'descending'
        }
        
        url = self.base_url + urllib.parse.urlencode(params)
        
        print(f"正在抓取 arXiv 论文...")
        print(f"查询: {search_query}")
        
        # 发送请求
        try:
            with urllib.request.urlopen(url) as response:
                data = response.read()
        except Exception as e:
            print(f"请求失败: {e}")
            return []
        
        # 解析 XML
        papers = self._parse_xml(data)
        
        print(f"成功抓取 {len(papers)} 篇论文")
        return papers
    
    def _parse_xml(self, xml_data: bytes) -> List[Dict]:
        """解析 arXiv API 返回的 XML 数据"""
        root = ET.fromstring(xml_data)
        papers = []
        
        for entry in root.findall('atom:entry', self.namespace):
            paper = {}
            
            # 基本信息
            paper['id'] = entry.find('atom:id', self.namespace).text
            paper['arxiv_id'] = paper['id'].split('/abs/')[-1]
            paper['title'] = entry.find('atom:title', self.namespace).text.strip().replace('\n', ' ')
            paper['summary'] = entry.find('atom:summary', self.namespace).text.strip().replace('\n', ' ')
            
            # 作者
            authors = []
            for author in entry.findall('atom:author', self.namespace):
                name = author.find('atom:name', self.namespace).text
                authors.append(name)
            paper['authors'] = authors
            
            # 日期
            published = entry.find('atom:published', self.namespace).text
            paper['published'] = published
            
            # 分类
            categories = []
            for category in entry.findall('atom:category', self.namespace):
                categories.append(category.get('term'))
            paper['categories'] = categories
            
            # PDF 链接
            for link in entry.findall('atom:link', self.namespace):
                if link.get('title') == 'pdf':
                    paper['pdf_url'] = link.get('href')
            
            papers.append(paper)
        
        return papers
    
    def save_to_json(self, papers: List[Dict], filename: str = None):
        """保存论文到 JSON 文件"""
        if filename is None:
            filename = f"arxiv_papers_{datetime.now().strftime('%Y%m%d')}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
        
        print(f"已保存到 {filename}")
    
    def format_paper(self, paper: Dict) -> str:
        """格式化单篇论文信息"""
        output = []
        output.append(f"标题: {paper['title']}")
        output.append(f"arXiv ID: {paper['arxiv_id']}")
        output.append(f"作者: {', '.join(paper['authors'][:3])}{'...' if len(paper['authors']) > 3 else ''}")
        output.append(f"分类: {', '.join(paper['categories'])}")
        output.append(f"发布日期: {paper['published'][:10]}")
        output.append(f"摘要: {paper['summary'][:200]}...")
        output.append(f"PDF: {paper.get('pdf_url', 'N/A')}")
        output.append("-" * 80)
        return '\n'.join(output)


def main():
    """主函数示例"""
    # 示例 1: 抓取所有 AI/ML/CV 相关论文
    print("=" * 80)
    print("示例 1: 抓取 AI/ML/CV 最近 1 天的论文")
    print("=" * 80)
    
    agent = ArxivAgent(categories=['cs.AI', 'cs.LG', 'cs.CV'])
    papers = agent.fetch_recent_papers(days=1, max_results=50)
    
    # 打印前 3 篇
    for i, paper in enumerate(papers[:3], 1):
        print(f"\n论文 {i}:")
        print(agent.format_paper(paper))
    
    # 保存到 JSON
    agent.save_to_json(papers)
    
    print(f"\n共抓取 {len(papers)} 篇论文")
    
    # 示例 2: 按关键词过滤
    print("\n" + "=" * 80)
    print("示例 2: 过滤包含 'transformer' 的论文")
    print("=" * 80)
    
    keyword = 'transformer'
    filtered = [p for p in papers if keyword.lower() in p['title'].lower() 
                or keyword.lower() in p['summary'].lower()]
    
    print(f"找到 {len(filtered)} 篇包含 '{keyword}' 的论文\n")
    for paper in filtered[:2]:
        print(agent.format_paper(paper))


if __name__ == '__main__':
    main()
