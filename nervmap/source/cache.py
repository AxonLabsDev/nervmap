"""SQLite incremental cache for parsed source files."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger("nervmap.source.cache")


class SourceCache:
    """Cache parsed source file data in SQLite.

    Algorithm:
    - Check mtime+size first (fast path).
    - If mtime/size changed, compute sha256.
    - Re-parse only if sha256 differs.
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = str(Path.home() / ".nervmap" / "cache.db")

        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS source_cache (
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                parsed_data TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def get(self, filepath: str) -> dict | None:
        """Get cached parse result if file is unchanged.

        Returns None if cache miss or file changed.
        """
        try:
            stat = os.stat(filepath)
        except OSError:
            return None

        cur = self._conn.execute(
            "SELECT mtime, size, sha256, parsed_data FROM source_cache WHERE path = ?",
            (filepath,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        cached_mtime, cached_size, cached_sha, cached_data = row

        # Fast path: mtime+size unchanged
        if stat.st_mtime == cached_mtime and stat.st_size == cached_size:
            try:
                return json.loads(cached_data)
            except json.JSONDecodeError:
                return None

        # mtime or size changed — check sha256
        current_sha = self._sha256(filepath)
        if current_sha == cached_sha:
            # File content unchanged, update mtime/size in cache
            self._conn.execute(
                "UPDATE source_cache SET mtime = ?, size = ? WHERE path = ?",
                (stat.st_mtime, stat.st_size, filepath),
            )
            self._conn.commit()
            try:
                return json.loads(cached_data)
            except json.JSONDecodeError:
                return None

        # Content changed — invalidate
        return None

    def store(self, filepath: str, data: dict) -> None:
        """Store parsed data for a file."""
        try:
            stat = os.stat(filepath)
        except OSError:
            return

        sha = self._sha256(filepath)
        json_data = json.dumps(data, default=str)

        self._conn.execute(
            """INSERT OR REPLACE INTO source_cache (path, mtime, size, sha256, parsed_data)
               VALUES (?, ?, ?, ?, ?)""",
            (filepath, stat.st_mtime, stat.st_size, sha, json_data),
        )
        self._conn.commit()

    @staticmethod
    def _sha256(filepath: str) -> str:
        """Compute SHA-256 of a file."""
        h = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
        except Exception:
            return ""
        return h.hexdigest()

    def close(self):
        """Close the database connection."""
        self._conn.close()
