"""
Persistent store for vlr.gg pages that no longer change.

A completed match's pages (overview, performance and economy tabs) are final,
so they are kept on disk instead of being refetched every few minutes or after
a restart. The store holds raw HTML, not parsed JSON: after a parser fix, data
is rebuilt from the stored pages without asking vlr.gg again.

The location comes from ``VLRGG_PAGE_STORE`` (a SQLite file path, see
``vlrgg.config``); an empty value disables the store.
"""
import logging
import os
import sqlite3
import time
import zlib
from pathlib import Path

from vlrgg import config

logger = logging.getLogger(__name__)


class PageStore:
    """URL -> HTML, zlib-compressed in a single SQLite table."""

    def __init__(self, path: str | os.PathLike | None):
        self.path = Path(path) if path else None
        self._ready = False

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        if not self._ready:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, html BLOB NOT NULL, stored_at REAL NOT NULL)"
            )
            self._ready = True
        return conn

    def get(self, url: str) -> str | None:
        if not self.enabled:
            return None
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT html FROM pages WHERE url = ?", (url,)).fetchone()
        except sqlite3.Error as exc:
            logger.warning("Page store read failed for %s: %s", url, exc)
            return None
        return zlib.decompress(row[0]).decode("utf-8") if row else None

    def put(self, url: str, html: str) -> None:
        if not self.enabled:
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO pages (url, html, stored_at) VALUES (?, ?, ?)",
                    (url, zlib.compress(html.encode("utf-8"), 6), time.time()),
                )
        except sqlite3.Error as exc:
            logger.warning("Page store write failed for %s: %s", url, exc)

    def delete(self, url: str) -> None:
        if not self.enabled:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM pages WHERE url = ?", (url,))

    def __len__(self) -> int:
        if not self.enabled:
            return 0
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]


page_store = PageStore(config.PAGE_STORE or None)
