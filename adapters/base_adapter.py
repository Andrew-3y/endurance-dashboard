"""
base_adapter.py — Abstract base class that ALL racing series adapters must implement.

WHY THIS EXISTS:
    Every racing series (IMSA, WEC, etc.) publishes timing data differently —
    different URLs, different JSON shapes, different field names.  But OUR app
    needs the data in ONE consistent format so that the leaderboard, anomaly
    detector, and predictor don't have to care which series they're looking at.

    This base class defines the contract:
        1. fetch_raw_data()  → go get the raw bytes / JSON from the internet
        2. parse_data()      → turn that raw blob into a list of Python dicts
        3. normalize_data()  → map those dicts into our unified schema
        4. get_data()        → convenience method that chains 1→2→3

HOW TO ADD A NEW SERIES (e.g. WEC):
    1. Create  adapters/wec_adapter.py
    2. Write   class WECAdapter(BaseAdapter)
    3. Implement the three abstract methods for WEC's data source
    4. Register the adapter in app.py  (one line change)
    That's it — every service downstream works automatically.
"""

from abc import ABC, abstractmethod
from typing import Any


# ─── Unified Schema ────────────────────────────────────────────────────
# Every adapter MUST produce dicts that contain AT LEAST these keys.
# Services rely on these field names.  If a field is unavailable from
# the source, set it to None — never omit the key.

NORMALIZED_FIELDS = [
    "series",              # e.g. "IMSA", "WEC"
    "event_name",          # e.g. "Rolex 24 At Daytona"
    "session_name",        # e.g. "Race", "Qualifying"
    "car_number",          # str, e.g. "01"
    "team_name",           # str
    "class_name",          # e.g. "GTP", "LMP2", "GTD"
    "current_driver",      # driver currently in the car
    "overall_position",    # int
    "class_position",      # int
    "laps_completed",      # int
    "gap_to_leader",       # str or float ("+1 Lap", "12.345")
    "gap_to_class_leader", # str or float
    "last_lap_time",       # float seconds, or None
    "best_lap_time",       # float seconds, or None
    "pit_status",          # "IN_PIT", "ON_TRACK", or None
    "pit_stops",           # int
    "timestamp",           # ISO-8601 string of when this snapshot was taken
]


class BaseAdapter(ABC):
    """Abstract interface for a racing-series data adapter."""

    @property
    @abstractmethod
    def series_name(self) -> str:
        """Return the human-readable series name (e.g. 'IMSA')."""

    @abstractmethod
    def fetch_raw_data(self) -> Any:
        """
        Fetch raw data from the series' public timing endpoint.
        Returns whatever the source gives you (JSON dict, XML string, etc.).
        Must raise AdapterError on failure.
        """

    @abstractmethod
    def parse_data(self, raw_data: Any) -> list[dict]:
        """
        Parse the raw data into a list of dicts — one dict per car.
        Field names can still be source-specific at this stage.
        """

    @abstractmethod
    def normalize_data(self, parsed_data: list[dict]) -> list[dict]:
        """
        Map source-specific fields into the unified NORMALIZED_FIELDS schema.
        Every dict in the returned list MUST contain all NORMALIZED_FIELDS keys.
        """

    def get_data(self) -> list[dict]:
        """
        Convenience: fetch → parse → normalize in one call.
        This is what the Flask app calls.
        """
        raw = self.fetch_raw_data()
        parsed = self.parse_data(raw)
        return self.normalize_data(parsed)


class AdapterError(Exception):
    """Raised when an adapter cannot fetch or parse data."""
