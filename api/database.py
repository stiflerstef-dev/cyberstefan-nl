import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "writeups.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS writeups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    machine     TEXT    NOT NULL,
    difficulty  TEXT    NOT NULL,
    platform    TEXT    NOT NULL,
    tags        TEXT    NOT NULL DEFAULT '[]',
    writeup     TEXT    NOT NULL DEFAULT '',
    writeup_nl  TEXT    NOT NULL DEFAULT '',
    linkedin    TEXT    NOT NULL DEFAULT '',
    linkedin_nl TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'Completed',
    created_at  TEXT    NOT NULL DEFAULT (date('now'))
);
"""

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Migratie: voeg linkedin_nl toe als die nog niet bestaat
        cols = [r[1] for r in conn.execute("PRAGMA table_info(writeups)").fetchall()]
        if "writeup_nl" not in cols:
            conn.execute("ALTER TABLE writeups ADD COLUMN writeup_nl TEXT NOT NULL DEFAULT ''")
            conn.commit()
        if "linkedin_nl" not in cols:
            conn.execute("ALTER TABLE writeups ADD COLUMN linkedin_nl TEXT NOT NULL DEFAULT ''")
            conn.commit()
