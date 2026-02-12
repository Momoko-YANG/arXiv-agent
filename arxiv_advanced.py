#!/usr/bin/env python3
"""
Advanced arXiv Agent with Database Storage
带数据库存储和去重的高级版本
"""

import sqlite3
from datetime import datetime
from typing import List, Dict, Optional
from arxiv_agent import ArxivAgent


class ArxivDatabase:
    """arXiv 论文数据库管理"""
    
    def __init__(self, db_path: str = "arxiv_papers.db"):
        """初始化数据库"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
    
    def _create_tables(self):
        """创建数据表"""
        cursor = self.conn.cursor()
        
        # 论文表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arxiv_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                published DATE,
                pdf_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 作者表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS authors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')
        
        # 论文-作者关联表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_authors (
                paper_id INTEGER,
                author_id INTEGER,
                author_order INTEGER,
                FOREIGN KEY (paper_id) REFERENCES papers(id),
                FOREIGN KEY (author_id) REFERENCES authors(id),
                PRIMARY KEY (paper_id, author_id)
            )
        ''')
        
        # 分类表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')
        
        # 论文-分类关联表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_categories (
                paper_id INTEGER,
                category_id INTEGER,
                FOREIGN KEY (paper_id) REFERENCES papers(id),
                FOREIGN KEY (category_id) REFERENCES categories(id),
                PRIMARY KEY (paper_id, category_id)
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_arxiv_id ON papers(arxiv_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_published ON papers(published)')
        
        self.conn.commit()
    
    def insert_paper(self, paper: Dict) -> bool:
        """
        插入论文到数据库
        
        Returns:
            True if new paper inserted, False if already exists
        """
        cursor = self.conn.cursor()
        
        try:
            # 插入论文基本信息
            cursor.execute('''
                INSERT INTO papers (arxiv_id, title, summary, published, pdf_url)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                paper['arxiv_id'],
                paper['title'],
                paper['summary'],
                paper['published'][:10],
                paper.get('pdf_url')
            ))
            
            paper_id = cursor.lastrowid
            
            # 插入作者
            for order, author_name in enumerate(paper['authors']):
                # 先尝试获取作者 ID
                cursor.execute('SELECT id FROM authors WHERE name = ?', (author_name,))
                row = cursor.fetchone()
                
                if row:
                    author_id = row[0]
                else:
                    cursor.execute('INSERT INTO authors (name) VALUES (?)', (author_name,))
                    author_id = cursor.lastrowid
                
                # 插入论文-作者关联
                cursor.execute('''
                    INSERT INTO paper_authors (paper_id, author_id, author_order)
                    VALUES (?, ?, ?)
                ''', (paper_id, author_id, order))
            
            # 插入分类
            for category_name in paper['categories']:
                cursor.execute('SELECT id FROM categories WHERE name = ?', (category_name,))
                row = cursor.fetchone()
                
                if row:
                    category_id = row[0]
                else:
                    cursor.execute('INSERT INTO categories (name) VALUES (?)', (category_name,))
                    category_id = cursor.lastrowid
                
                cursor.execute('''
                    INSERT INTO paper_categories (paper_id, category_id)
                    VALUES (?, ?)
                ''', (paper_id, category_id))
            
            self.conn.commit()
            return True
            
        except sqlite3.IntegrityError:
            # 论文已存在
            self.conn.rollback()
            return False
    
    def get_paper_by_arxiv_id(self, arxiv_id: str) -> Optional[Dict]:
        """根据 arXiv ID 获取论文"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM papers WHERE arxiv_id = ?', (arxiv_id,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def get_recent_papers(self, days: int = 7, limit: int = 100) -> List[Dict]:
        """获取最近的论文"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM papers 
            WHERE published >= date('now', '-{} days')
            ORDER BY published DESC
            LIMIT ?
        '''.format(days), (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def search_papers(self, keyword: str, limit: int = 50) -> List[Dict]:
        """搜索论文（标题或摘要）"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM papers 
            WHERE title LIKE ? OR summary LIKE ?
            ORDER BY published DESC
            LIMIT ?
        ''', (f'%{keyword}%', f'%{keyword}%', limit))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        cursor = self.conn.cursor()
        
        stats = {}
        
        # 总论文数
        cursor.execute('SELECT COUNT(*) FROM papers')
        stats['total_papers'] = cursor.fetchone()[0]
        
        # 总作者数
        cursor.execute('SELECT COUNT(*) FROM authors')
        stats['total_authors'] = cursor.fetchone()[0]
        
        # 分类统计
        cursor.execute('''
            SELECT c.name, COUNT(pc.paper_id) as count
            FROM categories c
            LEFT JOIN paper_categories pc ON c.id = pc.category_id
            GROUP BY c.name
            ORDER BY count DESC
        ''')
        stats['category_counts'] = {row[0]: row[1] for row in cursor.fetchall()}
        
        # 最近 7 天的论文数
        cursor.execute('''
            SELECT COUNT(*) FROM papers 
            WHERE published >= date('now', '-7 days')
        ''')
        stats['papers_last_7_days'] = cursor.fetchone()[0]
        
        return stats
    
    def close(self):
        """关闭数据库连接"""
        self.conn.close()


class AdvancedArxivAgent:
    """高级 arXiv Agent，带数据库存储"""
    
    def __init__(self, categories: List[str], db_path: str = "arxiv_papers.db"):
        """初始化"""
        self.agent = ArxivAgent(categories=categories)
        self.db = ArxivDatabase(db_path=db_path)
        self.categories = categories
    
    def sync_daily_papers(self, days: int = 1) -> Dict:
        """同步最近的论文到数据库"""
        print(f"开始同步最近 {days} 天的论文...")
        
        # 从 arXiv 抓取
        papers = self.agent.fetch_recent_papers(days=days, max_results=500)
        
        new_count = 0
        duplicate_count = 0
        
        for paper in papers:
            if self.db.insert_paper(paper):
                new_count += 1
            else:
                duplicate_count += 1
        
        print(f"同步完成: 新增 {new_count} 篇, 重复 {duplicate_count} 篇")
        
        return {
            'total': len(papers),
            'new': new_count,
            'duplicate': duplicate_count
        }
    
    def get_daily_digest(self, days: int = 1) -> str:
        """生成每日摘要"""
        papers = self.db.get_recent_papers(days=days, limit=200)
        
        digest = []
        digest.append(f"arXiv 每日摘要 ({len(papers)} 篇)")
        digest.append(f"日期范围: 最近 {days} 天")
        digest.append("=" * 80)
        digest.append("")
        
        for i, paper in enumerate(papers, 1):
            digest.append(f"{i}. {paper['title']}")
            digest.append(f"   ID: {paper['arxiv_id']} | 发布: {paper['published']}")
            digest.append("")
        
        return '\n'.join(digest)
    
    def print_stats(self):
        """打印统计信息"""
        stats = self.db.get_stats()
        
        print("\n" + "=" * 80)
        print("数据库统计")
        print("=" * 80)
        print(f"总论文数: {stats['total_papers']}")
        print(f"总作者数: {stats['total_authors']}")
        print(f"最近 7 天: {stats['papers_last_7_days']} 篇")
        print("\n分类统计:")
        for cat, count in sorted(stats['category_counts'].items(), 
                                key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {cat}: {count} 篇")
        print("=" * 80 + "\n")
    
    def close(self):
        """关闭数据库"""
        self.db.close()


def main():
    """示例用法"""
    categories = ['cs.AI', 'cs.LG', 'cs.CV', 'cs.CL']
    
    agent = AdvancedArxivAgent(categories=categories)
    
    try:
        # 同步最近 2 天的论文
        result = agent.sync_daily_papers(days=2)
        print(f"\n同步结果: {result}")
        
        # 打印统计信息
        agent.print_stats()
        
        # 搜索示例
        print("搜索包含 'diffusion' 的论文:")
        print("=" * 80)
        papers = agent.db.search_papers('diffusion', limit=5)
        for paper in papers:
            print(f"- {paper['title']}")
            print(f"  {paper['arxiv_id']} | {paper['published']}\n")
        
    finally:
        agent.close()


if __name__ == '__main__':
    main()
