"""
Tiny SQLite persistence layer: reading progress and highlights.
No ORM, no migrations framework — one file, one schema, matches the spirit of the rest of the project.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, Optional

DB_PATH = "reader3.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
    book_id TEXT PRIMARY KEY,
    chapter_index INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS highlights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT NOT NULL,
    chapter_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_highlights_book_chapter
    ON highlights (book_id, chapter_index);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as conn:
        conn.executescript(SCHEMA)


# --- Progress ---

def get_progress(book_id: str) -> Optional[int]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT chapter_index FROM progress WHERE book_id = ?", (book_id,)
        ).fetchone()
        return row["chapter_index"] if row else None


def set_progress(book_id: str, chapter_index: int):
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO progress (book_id, chapter_index, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(book_id) DO UPDATE SET
                chapter_index = excluded.chapter_index,
                updated_at = excluded.updated_at
            """,
            (book_id, chapter_index),
        )


def get_all_progress() -> dict:
    """book_id -> chapter_index, for the library view."""
    with _conn() as conn:
        rows = conn.execute("SELECT book_id, chapter_index FROM progress").fetchall()
        return {r["book_id"]: r["chapter_index"] for r in rows}


# --- Highlights ---

@dataclass
class Highlight:
    id: int
    book_id: str
    chapter_index: int
    text: str
    created_at: str


def add_highlight(book_id: str, chapter_index: int, text: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO highlights (book_id, chapter_index, text) VALUES (?, ?, ?)",
            (book_id, chapter_index, text),
        )
        return cur.lastrowid


def get_highlights(book_id: str, chapter_index: int) -> List[Highlight]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT id, book_id, chapter_index, text, created_at FROM highlights
            WHERE book_id = ? AND chapter_index = ?
            ORDER BY id ASC
            """,
            (book_id, chapter_index),
        ).fetchall()
        return [Highlight(**dict(r)) for r in rows]


def delete_highlight(highlight_id: int):
    with _conn() as conn:
        conn.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
