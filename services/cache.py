"""
cache.py — Simple time-based in-memory cache.

WHY:
    When a user refreshes the page, we don't want to hit IMSA's servers again
    if we just fetched data 5 seconds ago.  This cache stores the last result
    and returns it if it's still fresh.

HOW IT WORKS:
    - Store data with a timestamp.
    - On read, check if the data is older than `ttl` seconds.
    - If stale (or empty), return None so the caller knows to fetch fresh data.
    - This is in-memory only — restarting the app clears it.  That's fine for
      Render free tier where the app spins down anyway.

WHY NOT SQLITE:
    For a cache with 5-15 second TTL, writing to disk is wasteful.
    In-memory is faster and simpler.  We'd use SQLite only if we needed
    persistence across restarts (e.g., historical data).
"""

import time
from typing import Any


class SimpleCache:
    """Time-based in-memory cache with a configurable TTL (time-to-live)."""

    def __init__(self, ttl_seconds: int = 10):
        """
        Args:
            ttl_seconds: How many seconds cached data stays valid.
                         Default 10 — a good balance between freshness and
                         not overloading the data source.
        """
        self._ttl = ttl_seconds
        self._data: Any = None
        self._timestamp: float = 0.0

    def get(self) -> Any | None:
        """
        Return cached data if it's still fresh, otherwise None.

        Returns:
            The cached data, or None if expired/empty.
        """
        if self._data is None:
            return None
        age = time.time() - self._timestamp
        if age > self._ttl:
            return None  # stale
        return self._data

    def set(self, data: Any) -> None:
        """Store data in the cache with the current timestamp."""
        self._data = data
        self._timestamp = time.time()

    def clear(self) -> None:
        """Manually invalidate the cache."""
        self._data = None
        self._timestamp = 0.0

    @property
    def age_seconds(self) -> float:
        """How old the cached data is (seconds). 0 if empty."""
        if self._data is None:
            return 0.0
        return time.time() - self._timestamp
