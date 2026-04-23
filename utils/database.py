"""
SQLite 论文数据库管理

v3: 新增 user_feedback / agent_decisions 表，支持反馈闭环 + 自适应评分
"""

import sqlite3
import threading
from typing import List, Dict, Optional, Set


class ArxivDatabase:
    """arXiv 论文数据库"""

    def __init__(self, db_path: str = "arxiv_papers.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create_tables()

    def _create_tables(self):
        """创建数据表"""
        with self._lock:
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

            # ---- 用户反馈表 ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    arxiv_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    source_id TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_fb_arxiv ON user_feedback(arxiv_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_fb_time ON user_feedback(timestamp)')
            cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_fb_source ON user_feedback(source_id)')

            # ---- Agent 决策日志表 ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS agent_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date DATE NOT NULL,
                    total_fetched INTEGER DEFAULT 0,
                    total_recommended INTEGER DEFAULT 0,
                    avg_score REAL DEFAULT 0,
                    strategy_notes TEXT DEFAULT '',
                    scorer_weights TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

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

            try:
                cursor.execute("ALTER TABLE user_feedback ADD COLUMN source_id TEXT")
            except Exception:
                pass

            self.conn.commit()

    def insert_paper(self, paper: Dict) -> bool:
        """插入论文（返回 True = 新增，False = 已存在）"""
        with self._lock:
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
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM papers WHERE arxiv_id = ?', (arxiv_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_recent_papers(self, days: int = 7, limit: int = 100) -> List[Dict]:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                f"SELECT * FROM papers WHERE published >= date('now', '-{days} days') "
                f"ORDER BY quality_score DESC, published DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def search_papers(self, keyword: str, limit: int = 50) -> List[Dict]:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                'SELECT * FROM papers WHERE title LIKE ? OR summary LIKE ? '
                'ORDER BY quality_score DESC LIMIT ?',
                (f'%{keyword}%', f'%{keyword}%', limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict:
        with self._lock:
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

    # ------------------------------------------------------------------
    # 增量去重
    # ------------------------------------------------------------------

    def get_recent_ids(self, days: int = 7) -> Set[str]:
        """获取最近 N 天已入库的 arXiv ID 集合（用于去重）"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT arxiv_id FROM papers WHERE created_at >= datetime('now', ?)",
                (f'-{days} days',),
            )
            return {row[0] for row in cursor.fetchall()}

    # ------------------------------------------------------------------
    # 用户反馈
    # ------------------------------------------------------------------

    def add_feedback(self, arxiv_id: str, action: str,
                     source_id: str = None) -> bool:
        """
        记录用户反馈

        action: 'star' | 'dismiss' | 'read'
        """
        with self._lock:
            if source_id:
                cursor = self.conn.execute(
                    'INSERT OR IGNORE INTO user_feedback (arxiv_id, action, source_id) '
                    'VALUES (?, ?, ?)',
                    (arxiv_id, action, source_id),
                )
            else:
                cursor = self.conn.execute(
                    'INSERT INTO user_feedback (arxiv_id, action) VALUES (?, ?)',
                    (arxiv_id, action),
                )
            self.conn.commit()
            return cursor.rowcount > 0

    def get_feedback_stats(self, days: int = 30) -> Dict:
        """
        获取反馈统计（用于自适应评分）

        Returns:
            {
                'starred_ids': [...],
                'dismissed_ids': [...],
                'star_count': int,
                'dismiss_count': int,
                'starred_papers': [...]  # 带完整信息的 star 论文
            }
        """
        with self._lock:
            cursor = self.conn.cursor()
            stats = {}

            cursor.execute(
                "SELECT arxiv_id FROM user_feedback "
                "WHERE action = 'star' AND timestamp >= datetime('now', ?)",
                (f'-{days} days',),
            )
            stats['starred_ids'] = [row[0] for row in cursor.fetchall()]
            stats['star_count'] = len(stats['starred_ids'])

            cursor.execute(
                "SELECT arxiv_id FROM user_feedback "
                "WHERE action = 'dismiss' AND timestamp >= datetime('now', ?)",
                (f'-{days} days',),
            )
            stats['dismissed_ids'] = [row[0] for row in cursor.fetchall()]
            stats['dismiss_count'] = len(stats['dismissed_ids'])

            # 获取被 star 的论文完整信息（用于分析偏好）
            if stats['starred_ids']:
                placeholders = ','.join('?' * len(stats['starred_ids']))
                cursor.execute(
                    f"SELECT * FROM papers WHERE arxiv_id IN ({placeholders})",
                    stats['starred_ids'],
                )
                stats['starred_papers'] = [dict(row) for row in cursor.fetchall()]
            else:
                stats['starred_papers'] = []

            return stats

    # ------------------------------------------------------------------
    # Agent 决策日志
    # ------------------------------------------------------------------

    def log_decision(self, run_date: str, total_fetched: int,
                     total_recommended: int, avg_score: float,
                     strategy_notes: str = "", scorer_weights: str = ""):
        """记录一次运行的决策日志"""
        with self._lock:
            self.conn.execute(
                'INSERT INTO agent_decisions '
                '(run_date, total_fetched, total_recommended, avg_score, '
                'strategy_notes, scorer_weights) VALUES (?, ?, ?, ?, ?, ?)',
                (run_date, total_fetched, total_recommended, avg_score,
                 strategy_notes, scorer_weights),
            )
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()
