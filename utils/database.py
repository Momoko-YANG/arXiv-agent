"""
SQLite 论文数据库管理
"""

import sqlite3
from typing import List, Dict, Optional


class ArxivDatabase:
    """arXiv 论文数据库"""

    def __init__(self, db_path: str = "arxiv_papers.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """创建数据表"""
        cursor = self.conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arxiv_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                published DATE,
                pdf_url TEXT,
                citation_count INTEGER DEFAULT 0,
                influential_citation_count INTEGER DEFAULT 0,
                venue TEXT DEFAULT '',
                published_status INTEGER DEFAULT 0,
                journal TEXT DEFAULT '',
                doi TEXT DEFAULT '',
                quality_score REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS authors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')

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

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_categories (
                paper_id INTEGER,
                category_id INTEGER,
                FOREIGN KEY (paper_id) REFERENCES papers(id),
                FOREIGN KEY (category_id) REFERENCES categories(id),
                PRIMARY KEY (paper_id, category_id)
            )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_arxiv_id ON papers(arxiv_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_published ON papers(published)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_quality ON papers(quality_score)')

        # 自动迁移旧表
        for col, col_type in [
            ("citation_count", "INTEGER DEFAULT 0"),
            ("influential_citation_count", "INTEGER DEFAULT 0"),
            ("venue", "TEXT DEFAULT ''"),
            ("published_status", "INTEGER DEFAULT 0"),
            ("journal", "TEXT DEFAULT ''"),
            ("doi", "TEXT DEFAULT ''"),
            ("quality_score", "REAL DEFAULT 0"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE papers ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        self.conn.commit()

    def insert_paper(self, paper: Dict) -> bool:
        """插入论文（返回 True = 新增，False = 已存在）"""
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO papers (
                    arxiv_id, title, summary, published, pdf_url,
                    citation_count, influential_citation_count,
                    venue, published_status, journal, doi, quality_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                paper['arxiv_id'],
                paper['title'],
                paper['summary'],
                paper['published'][:10],
                paper.get('pdf_url'),
                paper.get('s2_citation_count', 0),
                paper.get('s2_influential_citation_count', 0),
                paper.get('s2_venue', ''),
                1 if paper.get('cr_published') else 0,
                paper.get('cr_journal', ''),
                paper.get('cr_doi', ''),
                paper.get('quality_score', 0),
            ))

            paper_id = cursor.lastrowid

            # 作者
            for order, author_name in enumerate(paper.get('authors', [])):
                cursor.execute('SELECT id FROM authors WHERE name = ?', (author_name,))
                row = cursor.fetchone()
                if row:
                    author_id = row[0]
                else:
                    cursor.execute('INSERT INTO authors (name) VALUES (?)', (author_name,))
                    author_id = cursor.lastrowid
                cursor.execute(
                    'INSERT INTO paper_authors (paper_id, author_id, author_order) VALUES (?, ?, ?)',
                    (paper_id, author_id, order),
                )

            # 分类
            for cat_name in paper.get('categories', []):
                cursor.execute('SELECT id FROM categories WHERE name = ?', (cat_name,))
                row = cursor.fetchone()
                if row:
                    cat_id = row[0]
                else:
                    cursor.execute('INSERT INTO categories (name) VALUES (?)', (cat_name,))
                    cat_id = cursor.lastrowid
                cursor.execute(
                    'INSERT INTO paper_categories (paper_id, category_id) VALUES (?, ?)',
                    (paper_id, cat_id),
                )

            self.conn.commit()
            return True

        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def get_paper_by_arxiv_id(self, arxiv_id: str) -> Optional[Dict]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM papers WHERE arxiv_id = ?', (arxiv_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_recent_papers(self, days: int = 7, limit: int = 100) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            f"SELECT * FROM papers WHERE published >= date('now', '-{days} days') "
            f"ORDER BY quality_score DESC, published DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def search_papers(self, keyword: str, limit: int = 50) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM papers WHERE title LIKE ? OR summary LIKE ? '
            'ORDER BY quality_score DESC LIMIT ?',
            (f'%{keyword}%', f'%{keyword}%', limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict:
        cursor = self.conn.cursor()
        stats = {}

        cursor.execute('SELECT COUNT(*) FROM papers')
        stats['total_papers'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM authors')
        stats['total_authors'] = cursor.fetchone()[0]

        cursor.execute('''
            SELECT c.name, COUNT(pc.paper_id) as count
            FROM categories c
            LEFT JOIN paper_categories pc ON c.id = pc.category_id
            GROUP BY c.name ORDER BY count DESC
        ''')
        stats['category_counts'] = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("SELECT COUNT(*) FROM papers WHERE published >= date('now', '-7 days')")
        stats['papers_last_7_days'] = cursor.fetchone()[0]

        return stats

    def close(self):
        self.conn.close()
