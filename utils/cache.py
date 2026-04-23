"""
磁盘缓存 — SQLite 实现，支持 TTL 自动过期

用于缓存 Semantic Scholar / Crossref 查询结果，避免重复 API 调用。
默认 TTL 7 天。
"""

import json
import os
import time
import sqlite3
import hashlib
import threading
from typing import Optional, Any


class DiskCache:
    """SQLite-backed disk cache with TTL"""

    def __init__(self, db_path: str = "data/cache/cache.db",
                 default_ttl: int = 7 * 86400):
        self.db_path = db_path
        self.default_ttl = default_ttl
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._lock = threading.RLock()
        self._create_table()

    def _create_table(self):
        with self._lock:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
            ''')
            self.conn.commit()

    @staticmethod
    def make_key(prefix: str, identifier: str) -> str:
        """生成缓存 key: prefix:md5(identifier)"""
        return f"{prefix}:{hashlib.md5(identifier.encode()).hexdigest()}"

    def get(self, key: str) -> Optional[Any]:
        """读取缓存，过期自动清除"""
        with self._lock:
            row = self.conn.execute(
                'SELECT value, expires_at FROM cache WHERE key = ?', (key,)
            ).fetchone()
            if row is None:
                return None
            if row[1] < time.time():
                self.conn.execute('DELETE FROM cache WHERE key = ?', (key,))
                self.conn.commit()
                return None
            return json.loads(row[0])

    def set(self, key: str, value: Any, ttl: int = None):
        """写入缓存"""
        ttl = ttl or self.default_ttl
        expires_at = time.time() + ttl
        with self._lock:
            self.conn.execute(
                'INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)',
                (key, json.dumps(value, ensure_ascii=False, default=str), expires_at),
            )
            self.conn.commit()

    def cleanup(self):
        """清理所有过期条目"""
        with self._lock:
            deleted = self.conn.execute(
                'DELETE FROM cache WHERE expires_at < ?', (time.time(),)
            ).rowcount
            self.conn.commit()
            return deleted

    def close(self):
        with self._lock:
            self.conn.close()
