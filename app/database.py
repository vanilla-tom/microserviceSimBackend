from __future__ import annotations

import aiosqlite

from app.config import settings

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending',
    progress        REAL DEFAULT 0.0,
    pid             INTEGER,
    config_path     TEXT,
    output_dir      TEXT,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    start_time      TEXT,
    end_time        TEXT,
    real_start_time INTEGER
)
"""

# Migration: add real_start_time column if not exists
_ADD_COLUMN_SQL = """
ALTER TABLE tasks ADD COLUMN real_start_time INTEGER
"""

_db: aiosqlite.Connection | None = None


async def init_db() -> None:
    global _db
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(str(settings.DB_PATH))
    _db.row_factory = aiosqlite.Row
    await _db.execute(_CREATE_TABLE_SQL)
    await _db.commit()

    # Migration: add real_start_time column if not exists
    try:
        await _db.execute(_ADD_COLUMN_SQL)
        await _db.commit()
    except aiosqlite.OperationalError:
        # Column already exists, ignore
        pass


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
