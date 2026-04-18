"""
alkamel_live.py - Lightweight live feed metadata client for Al Kamel IMSA timing.

This intentionally does not try to mirror the full live timing application.
Instead, it uses the live Meteor/DDP feed to extract stable, high-value data:
    - whether the IMSA live feed is running
    - the live feed's official results URL
    - published session IDs
    - session schedule documents available from the live service

That lets the dashboard make real use of the Al Kamel live endpoint without
depending on the full browser app.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

try:
    from websocket import create_connection
except ImportError:  # pragma: no cover - handled gracefully at runtime
    create_connection = None

logger = logging.getLogger(__name__)

ALKAMEL_LIVE_WS_URL = "wss://livetiming.alkamelsystems.com/websocket"
IMSA_FEED_NAME = "imsa"


def get_alkamel_live_feed_data() -> dict[str, Any] | None:
    """Return best-effort live feed metadata for the IMSA Al Kamel app."""
    if create_connection is None:
        return None

    ws = None
    try:
        ws = create_connection(ALKAMEL_LIVE_WS_URL, timeout=3)
        _recv_json(ws)  # initial server_id
        _send_json(ws, {"msg": "connect", "version": "1", "support": ["1", "pre2", "pre1"]})
        _recv_until(ws, lambda msg: msg.get("msg") == "connected", timeout_seconds=3)

        _send_json(ws, {"msg": "sub", "id": "feeds", "name": "feedsPublicsAndRunning", "params": []})
        feed_messages = _recv_many(ws, timeout_seconds=2.5)
        imsa_feed = _extract_imsa_feed(feed_messages)
        if not imsa_feed:
            return None

        sessions_param = imsa_feed.get("sessions", [])
        _send_json(ws, {"msg": "sub", "id": "sessions", "name": "sessions", "params": [sessions_param]})
        session_messages = _recv_many(ws, timeout_seconds=2.5)
        sessions = _extract_sessions(session_messages)

        return {
            "feed_name": imsa_feed.get("name", IMSA_FEED_NAME),
            "running": bool(imsa_feed.get("running")),
            "results_url": imsa_feed.get("resultsURL") or "",
            "session_count": len(imsa_feed.get("sessions", [])),
            "next_message_html": imsa_feed.get("noSessionMsg") or "",
            "next_message_text": _html_to_text(imsa_feed.get("noSessionMsg") or ""),
            "sessions": sessions,
        }
    except Exception:
        logger.exception("Failed fetching Al Kamel live feed data")
        return None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def _send_json(ws: Any, payload: dict[str, Any]) -> None:
    ws.send(json.dumps(payload))


def _recv_json(ws: Any) -> dict[str, Any]:
    return json.loads(ws.recv())


def _recv_until(ws: Any, predicate: Any, timeout_seconds: float) -> dict[str, Any] | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        msg = _recv_json(ws)
        if predicate(msg):
            return msg
    return None


def _recv_many(ws: Any, timeout_seconds: float) -> list[dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    messages: list[dict[str, Any]] = []
    while time.time() < deadline:
        try:
            messages.append(_recv_json(ws))
        except Exception:
            break
    return messages


def _extract_imsa_feed(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in messages:
        if message.get("msg") != "added" or message.get("collection") != "feeds":
            continue
        fields = message.get("fields", {})
        if fields.get("name") == IMSA_FEED_NAME:
            return fields
    return None


def _extract_sessions(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for message in messages:
        if message.get("msg") != "added" or message.get("collection") != "sessions":
            continue
        fields = message.get("fields", {})
        rows.append(
            {
                "id": message.get("id"),
                "name": fields.get("name") or "Unknown Session",
                "date": _format_timestamp(fields.get("date")),
                "end_date": _format_timestamp(fields.get("endDate")),
                "utc_offset_min": fields.get("UtcOffsetMin"),
            }
        )
    rows.sort(key=lambda row: row.get("date") or "")
    return rows


def _format_timestamp(raw: Any) -> str | None:
    try:
        value = int(raw) / 1000
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _html_to_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()
