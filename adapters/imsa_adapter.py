"""
imsa_adapter.py — Fetches live timing data from IMSA's public scoring endpoints.

═══════════════════════════════════════════════════════════════════════════
HOW IMSA TIMING DATA WORKS (BEGINNER EXPLANATION)
═══════════════════════════════════════════════════════════════════════════

When you visit IMSA's live timing page during a race, your browser makes
HTTP requests to fetch JSON data behind the scenes.  You can see these
yourself:

    1. Go to https://www.imsa.com/scoring/ during a live session.
    2. Open your browser's Developer Tools  (F12 or Ctrl+Shift+I).
    3. Click the "Network" tab.
    4. Filter by "XHR" or "Fetch".
    5. Refresh the page.
    6. Look for requests returning JSON — those are the timing endpoints.

IMSA uses a publicly accessible scoring API.  The main endpoint pattern is:

    https://scoring.imsa.com/scoring_data/SessionInfo.json
    https://scoring.imsa.com/scoring_data/SessionResults.json

These URLs may change between events.  The adapter below handles this by
trying known endpoint patterns and gracefully failing if none work.

IMPORTANT ETHICS NOTE:
    - We fetch data ONCE per page load (with caching).
    - We never hammer the endpoint in a loop.
    - We set a polite User-Agent header.
    - This is public data served to every browser that visits the page.
═══════════════════════════════════════════════════════════════════════════
"""

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from adapters.base_adapter import AdapterError, BaseAdapter

logger = logging.getLogger(__name__)

# ─── Known IMSA Endpoints ──────────────────────────────────────────────
# IMSA's scoring system is hosted at scoring.imsa.com.  The exact paths
# can shift between seasons, so we try multiple known patterns.

IMSA_BASE_URLS = [
    "https://scoring.imsa.com",
]

SESSION_INFO_PATHS = [
    "/scoring_data/SessionInfo.json",
]

SESSION_RESULTS_PATHS = [
    "/scoring_data/SessionResults.json",
]

REQUEST_TIMEOUT = 10  # seconds — fail fast on Render free tier
USER_AGENT = "EnduranceDashboard/1.0 (educational project)"


def _try_fetch(base_urls: list[str], paths: list[str]) -> dict | None:
    """Try every combination of base URL + path until one works."""
    for base in base_urls:
        for path in paths:
            url = base + path
            try:
                resp = requests.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    headers={"User-Agent": USER_AGENT},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data:  # non-empty
                        logger.info("Fetched data from %s", url)
                        return data
            except (requests.RequestException, ValueError) as exc:
                logger.debug("Failed %s: %s", url, exc)
                continue
    return None


def _parse_lap_time(raw: Any) -> float | None:
    """
    Convert a lap time string like "1:34.567" or "94.567" to total seconds.
    Returns None if unparseable.
    """
    if raw is None or raw == "" or raw == "--":
        return None
    try:
        s = str(raw).strip()
        if ":" in s:
            parts = s.split(":")
            return float(parts[0]) * 60 + float(parts[1])
        return float(s)
    except (ValueError, IndexError):
        return None


class IMSAAdapter(BaseAdapter):
    """
    Adapter for IMSA (International Motor Sports Association) live timing.

    Implements the BaseAdapter contract:
        fetch_raw_data  → hits IMSA's public JSON endpoints
        parse_data      → extracts the car entries from the JSON structure
        normalize_data  → maps IMSA field names to our unified schema
    """

    @property
    def series_name(self) -> str:
        return "IMSA"

    def fetch_raw_data(self) -> dict:
        """
        Fetch both session info and results from IMSA's public endpoints.
        Returns a dict with keys 'session_info' and 'results'.
        Raises AdapterError if no data can be retrieved.
        """
        session_info = _try_fetch(IMSA_BASE_URLS, SESSION_INFO_PATHS)
        results = _try_fetch(IMSA_BASE_URLS, SESSION_RESULTS_PATHS)

        if results is None:
            raise AdapterError(
                "Could not fetch IMSA timing data. "
                "There may be no active session, or the endpoints have changed. "
                "Check https://www.imsa.com/scoring/ to verify."
            )

        return {
            "session_info": session_info or {},
            "results": results,
        }

    def parse_data(self, raw_data: dict) -> list[dict]:
        """
        Extract the list of car entries from IMSA's JSON structure.

        IMSA's SessionResults.json typically has a structure like:
            { "params": {...}, "results": [ {car1}, {car2}, ... ] }
        or sometimes the results are at the top level as a list.

        We handle both shapes.
        """
        results = raw_data.get("results", {})
        session_info = raw_data.get("session_info", {})

        # Extract the car list — IMSA nests this differently depending on
        # the event/year, so we try several known shapes.
        cars = []
        if isinstance(results, list):
            cars = results
        elif isinstance(results, dict):
            # Try common keys where the car array lives
            for key in ("results", "Results", "entries", "Entries", "scoring"):
                if key in results and isinstance(results[key], list):
                    cars = results[key]
                    break
            if not cars:
                # Maybe the entire dict is keyed by class
                for value in results.values():
                    if isinstance(value, list) and len(value) > 0:
                        cars.extend(value)

        if not cars:
            raise AdapterError(
                "IMSA returned data but we could not find car entries. "
                "The JSON structure may have changed."
            )

        # Attach session-level metadata to each car entry for normalization
        for car in cars:
            car["_session_info"] = session_info

        return cars

    def normalize_data(self, parsed_data: list[dict]) -> list[dict]:
        """
        Map IMSA-specific field names to our unified schema.

        IMSA's JSON uses field names like:
            "Number", "ClassID", "CurrentDriverName", "OverallPosition", etc.

        We map every known variant to our standard fields.  Unknown fields
        get None — that's fine, the UI handles missing data gracefully.
        """
        now = datetime.now(timezone.utc).isoformat()
        normalized = []

        for car in parsed_data:
            session_info = car.pop("_session_info", {})

            entry = {
                "series": "IMSA",
                "event_name": _get_first(session_info, [
                    "EventName", "event_name", "eventName", "Name",
                ]) or _get_first(car, ["EventName", "event_name"]) or "Unknown Event",
                "session_name": _get_first(session_info, [
                    "SessionName", "session_name", "sessionName", "Session",
                ]) or _get_first(car, ["SessionName", "session_name"]) or "Unknown Session",
                "car_number": str(_get_first(car, [
                    "Number", "number", "CarNumber", "car_number", "#",
                ]) or "?"),
                "team_name": _get_first(car, [
                    "Team", "TeamName", "team_name", "team",
                ]) or "Unknown Team",
                "class_name": _get_first(car, [
                    "Class", "ClassID", "class_name", "ClassName", "class",
                ]) or "Unknown",
                "current_driver": _get_first(car, [
                    "CurrentDriver", "CurrentDriverName", "current_driver",
                    "DriverName", "Driver", "driver_name",
                ]) or _extract_driver_name(car) or "Unknown Driver",
                "overall_position": _safe_int(_get_first(car, [
                    "OverallPosition", "Position", "overall_position",
                    "Pos", "position", "OverallPos",
                ])),
                "class_position": _safe_int(_get_first(car, [
                    "ClassPosition", "InClassPosition", "class_position",
                    "ClassPos", "PIC",
                ])),
                "laps_completed": _safe_int(_get_first(car, [
                    "Laps", "LapsCompleted", "laps_completed",
                    "TotalLaps", "laps",
                ])) or 0,
                "gap_to_leader": _get_first(car, [
                    "GapToLeader", "Gap", "gap_to_leader",
                    "OverallGap", "GapFirst",
                ]) or "--",
                "gap_to_class_leader": _get_first(car, [
                    "GapToClassLeader", "ClassGap", "gap_to_class_leader",
                    "InClassGap", "GapClassFirst",
                ]) or "--",
                "last_lap_time": _parse_lap_time(_get_first(car, [
                    "LastLapTime", "LastLap", "last_lap_time",
                    "LastTime", "last_lap",
                ])),
                "best_lap_time": _parse_lap_time(_get_first(car, [
                    "BestLapTime", "BestLap", "best_lap_time",
                    "BestTime", "best_lap", "FastestLap",
                ])),
                "pit_status": _parse_pit_status(_get_first(car, [
                    "InPit", "PitStatus", "pit_status",
                    "Status", "InPits", "is_in_pit",
                ])),
                "pit_stops": _safe_int(_get_first(car, [
                    "PitStops", "Pits", "pit_stops",
                    "NumberOfPitStops", "TotalPitStops",
                ])) or 0,
                "timestamp": now,
            }

            normalized.append(entry)

        # Sort by overall position
        normalized.sort(key=lambda x: x["overall_position"] or 9999)

        return normalized


# ─── Helper Functions ───────────────────────────────────────────────────

def _get_first(data: dict, keys: list[str]) -> Any:
    """Return the value for the first key that exists and is not None."""
    for key in keys:
        val = data.get(key)
        if val is not None:
            return val
    return None


def _safe_int(val: Any) -> int | None:
    """Convert a value to int, returning None if impossible."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _extract_driver_name(car: dict) -> str | None:
    """
    Some IMSA feeds put drivers in a nested list like:
        "Drivers": [{"Name": "...", "IsCurrentDriver": true}, ...]
    This helper tries to extract the current driver from that.
    """
    drivers = car.get("Drivers") or car.get("drivers") or []
    if not isinstance(drivers, list):
        return None
    for d in drivers:
        if isinstance(d, dict):
            is_current = d.get("IsCurrentDriver") or d.get("is_current")
            if is_current:
                return d.get("Name") or d.get("name") or d.get("DriverName")
    # If none flagged as current, return the first driver
    if drivers and isinstance(drivers[0], dict):
        return drivers[0].get("Name") or drivers[0].get("name")
    return None


def _parse_pit_status(val: Any) -> str:
    """Normalize pit status into 'IN_PIT' or 'ON_TRACK'."""
    if val is None:
        return "ON_TRACK"
    s = str(val).strip().upper()
    if s in ("TRUE", "1", "YES", "IN_PIT", "IN PIT", "PIT", "IN"):
        return "IN_PIT"
    return "ON_TRACK"
