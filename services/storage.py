"""
storage.py - SQLite persistence for live snapshots and historical sessions.

WHY:
    The in-memory cache is perfect for short TTL reads, but it disappears on
    process restart. This module provides lightweight persistence so the
    dashboard can still be useful when no live IMSA session is active.
"""

import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from services.session_analyzer import detect_session_type

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DASHBOARD_DB_PATH", "dashboard.sqlite")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_storage() -> None:
    """Create required tables if they do not exist yet."""
    with closing(_get_connection()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT UNIQUE NOT NULL,
                series TEXT NOT NULL,
                event_name TEXT NOT NULL,
                session_name TEXT NOT NULL,
                session_type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_session_data(series: str, entries: list[dict]) -> int | None:
    """
    Save (or update) a session snapshot in SQLite.
    Returns the session id when successful.
    """
    if not entries:
        return None

    init_storage()

    first = entries[0]
    event_name = str(first.get("event_name") or "Unknown Event")
    session_name = str(first.get("session_name") or "Unknown Session")
    session_type = str(first.get("session_type") or detect_session_type(session_name))
    session_key = f"{series.lower()}|{event_name}|{session_name}"
    now = _utc_now_iso()
    data_json = json.dumps(entries)

    with closing(_get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_key, series, event_name, session_name, session_type,
                data_json, last_updated, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                session_type = excluded.session_type,
                data_json = excluded.data_json,
                last_updated = excluded.last_updated
            """,
            (
                session_key,
                series.upper(),
                event_name,
                session_name,
                session_type,
                data_json,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT id FROM sessions WHERE session_key = ?",
            (session_key,),
        ).fetchone()
        conn.commit()
        return int(row["id"]) if row else None


def list_available_sessions(series: str | None = None) -> list[dict[str, Any]]:
    """
    Return all stored sessions, newest first.
    """
    init_storage()

    query = """
        SELECT id, series, event_name, session_name, session_type, last_updated
        FROM sessions
    """
    params: tuple[Any, ...] = ()
    if series:
        query += " WHERE LOWER(series) = ?"
        params = (series.lower(),)
    query += " ORDER BY last_updated DESC"

    with closing(_get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()

    sessions = []
    for row in rows:
        sessions.append(
            {
                "session_id": int(row["id"]),
                "series": row["series"],
                "event_name": row["event_name"],
                "session_name": row["session_name"],
                "session_type": row["session_type"],
                "last_updated": row["last_updated"],
            }
        )
    return sessions


def get_latest_session(series: str | None = None) -> dict[str, Any] | None:
    """Return the latest stored session metadata, or None if storage is empty."""
    sessions = list_available_sessions(series=series)
    return sessions[0] if sessions else None


def load_session_data(session_id: int | str) -> list[dict]:
    """
    Load stored entries for a given session id.
    Returns an empty list for unknown/invalid sessions.
    """
    init_storage()

    try:
        sid = int(session_id)
    except (TypeError, ValueError):
        return []

    with closing(_get_connection()) as conn:
        row = conn.execute(
            "SELECT data_json FROM sessions WHERE id = ?",
            (sid,),
        ).fetchone()

    if not row:
        return []

    try:
        data = json.loads(row["data_json"])
    except json.JSONDecodeError:
        logger.warning("Corrupt JSON for session id=%s", sid)
        return []

    return data if isinstance(data, list) else []
