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
        if not isinstance(entry, dict):
            logger.warning("Skipping non-dict entry in validate_entries: %r", entry)
            continue

        normalized = dict(entry)
        for field in NORMALIZED_FIELDS:
            if field not in normalized:
                normalized[field] = None

        # Normalize/correct high-risk fields to reduce faulty downstream data.
        normalized["series"] = _to_clean_str(normalized.get("series"))
        normalized["event_name"] = _to_clean_str(normalized.get("event_name"))
        normalized["session_name"] = _to_clean_str(normalized.get("session_name"))
        normalized["car_number"] = _to_clean_str(normalized.get("car_number")) or "?"
        normalized["team_name"] = _to_clean_str(normalized.get("team_name")) or "Unknown Team"
        normalized["class_name"] = _to_clean_str(normalized.get("class_name")) or "Unknown"
        normalized["current_driver"] = _to_clean_str(normalized.get("current_driver")) or "Unknown Driver"
        normalized["overall_position"] = _to_positive_int_or_none(normalized.get("overall_position"))
        normalized["class_position"] = _to_positive_int_or_none(normalized.get("class_position"))
        normalized["laps_completed"] = _to_non_negative_int(normalized.get("laps_completed"), default=0)
        normalized["pit_stops"] = _to_non_negative_int(normalized.get("pit_stops"), default=0)
        normalized["last_lap_time"] = _to_positive_float_or_none(normalized.get("last_lap_time"))
        normalized["best_lap_time"] = _to_positive_float_or_none(normalized.get("best_lap_time"))
        normalized["pit_status"] = _normalize_pit_status(normalized.get("pit_status"))
        normalized["gap_to_leader"] = _normalize_gap(normalized.get("gap_to_leader"))
        normalized["gap_to_class_leader"] = _normalize_gap(normalized.get("gap_to_class_leader"))
        normalized["timestamp"] = _to_clean_str(normalized.get("timestamp"))

        clean.append(normalized)
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
        val = float(gap)
        return val if val >= 0 else None
    s = str(gap).strip()
    if not s or s == "--" or "lap" in s.lower():
        return None
    if s.startswith("+"):
        s = s[1:]
    if s.endswith("s") or s.endswith("S"):
        s = s[:-1]
    s = s.strip().replace(",", "")
    try:
        val = float(s)
        return val if val >= 0 else None
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


def _to_clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        val = int(value)
    except (TypeError, ValueError):
        return default
    return val if val >= 0 else default


def _to_positive_int_or_none(value: Any) -> int | None:
    try:
        val = int(value)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _to_positive_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _normalize_pit_status(value: Any) -> str:
    if value is None:
        return "ON_TRACK"
    s = str(value).strip().upper()
    if s in ("IN_PIT", "IN PIT", "PIT", "IN", "TRUE", "1", "YES"):
        return "IN_PIT"
    return "ON_TRACK"


def _normalize_gap(value: Any) -> str | float:
    if value is None:
        return "--"
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    return text if text else "--"
