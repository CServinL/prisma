"""Lightweight SQLite key-value store for Prisma server state.

Namespaces keep concerns isolated. Any component can persist and query
past state without coupling to other components.

Usage:
    db = LocalDB()
    db.set("graphify:mtimes:/vault", "sources/paper.md", 1234567890.1)
    db.get("graphify:mtimes:/vault", "sources/paper.md")  # → 1234567890.1
    db.get_namespace("graphify:mtimes:/vault")             # → {key: value, ...}
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".local" / "share" / "prisma" / "prisma.db"


class LocalDB:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS kv (
                namespace  TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (namespace, key)
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_kv_ns ON kv (namespace)"
        )
        self._conn.commit()

    # ── Single-key ops ────────────────────────────────────────────────────────

    def get(self, namespace: str, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM kv WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, namespace: str, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (namespace, key, value, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (namespace, key, json.dumps(value), time.time()),
            )
            self._conn.commit()

    def delete(self, namespace: str, key: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM kv WHERE namespace=? AND key=?", (namespace, key)
            )
            self._conn.commit()

    # ── Namespace ops ─────────────────────────────────────────────────────────

    def get_namespace(self, namespace: str) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM kv WHERE namespace=?", (namespace,)
            ).fetchall()
        return {k: json.loads(v) for k, v in rows}

    def set_many(self, namespace: str, items: dict) -> None:
        now = time.time()
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO kv (namespace, key, value, updated_at)"
                " VALUES (?, ?, ?, ?)",
                [(namespace, k, json.dumps(v), now) for k, v in items.items()],
            )
            self._conn.commit()

    def clear_namespace(self, namespace: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE namespace=?", (namespace,))
            self._conn.commit()

    # ── Introspection ─────────────────────────────────────────────────────────

    def namespaces(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT namespace FROM kv ORDER BY namespace"
            ).fetchall()
        return [r[0] for r in rows]

    def count(self, namespace: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM kv WHERE namespace=?", (namespace,)
            ).fetchone()
        return row[0] if row else 0
