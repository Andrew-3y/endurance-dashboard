"""
data_normalizer.py — Validates and enriches normalized data.

WHY THIS EXISTS:
    After an adapter normalizes data, we run it through this service to:
    1. Validate that all required fields are present.
    2. Compute derived fields (like gap in seconds for analysis).
    3. Group cars by class for the class-specific leaderboards.

    This keeps validation logic out of the adapters — they just map fields,
    and this service ensures quality.
"""

import logging
from typing import Any

from adapters.base_adapter import NORMALIZED_FIELDS

logger = logging.getLogger(__name__)


def validate_entries(entries: list[dict]) -> list[dict]:
    """
    Ensure every entry has all NORMALIZED_FIELDS keys.
    Missing keys get set to None.  This prevents KeyError crashes
    in templates and downstream services.
    """
    clean = []
    for entry in entries:
        for field in NORMALIZED_FIELDS:
            if field not in entry:
                entry[field] = None
        clean.append(entry)
    return clean


def group_by_class(entries: list[dict]) -> dict[str, list[dict]]:
    """
    Group entries by class_name, sorted by class_position within each group.

    Returns:
        Dict mapping class name → list of car entries.
        Example: {"GTP": [{car1}, {car2}], "LMP2": [{car3}], ...}
    """
    classes: dict[str, list[dict]] = {}
    for entry in entries:
        cls = entry.get("class_name") or "Unknown"
        classes.setdefault(cls, []).append(entry)

    # Sort each class by class_position
    for cls in classes:
        classes[cls].sort(key=lambda x: x.get("class_position") or 9999)

    return classes


def parse_gap_to_seconds(gap: Any) -> float | None:
    """
    Try to convert a gap value to a float (seconds).

    IMSA gaps come in several formats:
        "12.345"      → 12.345  (seconds behind)
        "+1 Lap"      → None    (can't compare as seconds)
        "--"          → None    (no data)
        ""            → None
        12.345        → 12.345  (already a number)

    Returns None for anything that isn't a plain number of seconds.
    """
    if gap is None:
        return None
    if isinstance(gap, (int, float)):
        return float(gap)
    s = str(gap).strip()
    if not s or s == "--" or "lap" in s.lower():
        return None
    try:
        return float(s)
    except ValueError:
        return None


def format_lap_time(seconds: float | None) -> str:
    """
    Format seconds (e.g., 94.567) as "1:34.567" for display.
    Returns "--" if None.
    """
    if seconds is None:
        return "--"
    minutes = int(seconds // 60)
    secs = seconds - (minutes * 60)
    if minutes > 0:
        return f"{minutes}:{secs:06.3f}"
    return f"{secs:.3f}"


def get_event_info(entries: list[dict]) -> dict:
    """
    Extract event-level metadata from the first entry.
    Returns dict with series, event_name, session_name, session_type.
    """
    from services.session_analyzer import detect_session_type

    if not entries:
        return {
            "series": "Unknown",
            "event_name": "No Active Session",
            "session_name": "--",
            "session_type": "race",
        }
    first = entries[0]
    session_name = first.get("session_name") or "Unknown Session"
    return {
        "series": first.get("series") or "Unknown",
        "event_name": first.get("event_name") or "Unknown Event",
        "session_name": session_name,
        "session_type": detect_session_type(session_name),
    }
