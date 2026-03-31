from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from .utils import now_iso


# ── schema bootstrap ───────────────────────────────────────────────────
def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notebooks (
          notebook_id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          folder_path TEXT NOT NULL UNIQUE,
          metadata_path TEXT NOT NULL UNIQUE,
          created_via TEXT NOT NULL,
          last_synced_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
          source_id TEXT PRIMARY KEY,
          notebook_id TEXT NOT NULL,
          title TEXT NOT NULL,
          file_path TEXT NOT NULL UNIQUE,
          source_type TEXT,
          source_url TEXT,
          content_hash TEXT NOT NULL,
          created_via TEXT NOT NULL,
          last_synced_at TEXT NOT NULL,
          FOREIGN KEY (notebook_id) REFERENCES notebooks(notebook_id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()


# ── open / context manager ─────────────────────────────────────────────
def open_db(state_db: Path) -> sqlite3.Connection:
    state_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


@contextmanager
def db_connection(state_db: Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that opens a DB connection and ensures it is closed."""
    conn = open_db(state_db)
    try:
        yield conn
    finally:
        conn.close()


# ── upsert helpers ─────────────────────────────────────────────────────
def upsert_notebook(
    conn: sqlite3.Connection,
    *,
    notebook_id: str,
    title: str,
    folder_path: Path,
    metadata_path: Path,
    created_via: str,
) -> None:
    conn.execute(
        """
        INSERT INTO notebooks (notebook_id, title, folder_path, metadata_path, created_via, last_synced_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(notebook_id) DO UPDATE SET
          title = excluded.title,
          folder_path = excluded.folder_path,
          metadata_path = excluded.metadata_path,
          created_via = excluded.created_via,
          last_synced_at = excluded.last_synced_at
        """,
        (notebook_id, title, str(folder_path), str(metadata_path), created_via, now_iso()),
    )
    conn.commit()


def upsert_source(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    notebook_id: str,
    title: str,
    file_path: Path,
    source_type: str | None,
    source_url: str | None,
    content_hash: str,
    created_via: str,
) -> None:
    conn.execute(
        """
        INSERT INTO sources (
          source_id, notebook_id, title, file_path, source_type, source_url, content_hash, created_via, last_synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
          notebook_id = excluded.notebook_id,
          title = excluded.title,
          file_path = excluded.file_path,
          source_type = excluded.source_type,
          source_url = excluded.source_url,
          content_hash = excluded.content_hash,
          created_via = excluded.created_via,
          last_synced_at = excluded.last_synced_at
        """,
        (
            source_id,
            notebook_id,
            title,
            str(file_path),
            source_type,
            source_url,
            content_hash,
            created_via,
            now_iso(),
        ),
    )
    conn.commit()


# ── delete helpers ─────────────────────────────────────────────────────
def remove_notebook_state(conn: sqlite3.Connection, notebook_id: str) -> None:
    conn.execute("DELETE FROM notebooks WHERE notebook_id = ?", (notebook_id,))
    conn.commit()


def remove_source_state(conn: sqlite3.Connection, source_id: str) -> None:
    conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
    conn.commit()


def purge_notebook_state(conn: sqlite3.Connection, notebook_id: str) -> None:
    conn.execute("DELETE FROM sources WHERE notebook_id = ?", (notebook_id,))
    conn.execute("DELETE FROM notebooks WHERE notebook_id = ?", (notebook_id,))
    conn.commit()


# ── failure log ────────────────────────────────────────────────────────
def append_failure(sp: Any, payload: dict[str, Any]) -> None:
    sp.state_dir.mkdir(parents=True, exist_ok=True)
    enriched = {"ts": now_iso(), **payload}
    with sp.failure_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(enriched, ensure_ascii=False) + "\n")
