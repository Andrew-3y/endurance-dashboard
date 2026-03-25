"""
anomaly_detector.py — Detects unusual events during a race.

WHY THIS IS VALUABLE:
    Endurance races are long (6-24 hours).  It's easy to miss key moments.
    This service scans the timing data and flags things like:
        - A car suddenly going much slower (possible mechanical issue)
        - A car dropping multiple positions (incident? penalty?)
        - A car that's in the pits unexpectedly

HOW IT WORKS (SINGLE-SNAPSHOT):
    We only have ONE snapshot of data (the current state when the page loads).
    We can't compare "before vs. after" because we don't store history.

    So we use STATISTICAL ANOMALIES within the current snapshot:
        - Compare each car's last lap to their best lap.
        - Compare each car's last lap to the class average.
        - Flag cars that are significantly off pace.

    If we added SQLite history later, we could also detect:
        - Position changes over time
        - Stint degradation trends
        - Pit stop timing anomalies
"""

import logging

from services.data_normalizer import parse_gap_to_seconds

logger = logging.getLogger(__name__)

# ─── Thresholds (tunable) ──────────────────────────────────────────────
# A car whose last lap is this many seconds slower than their best is flagged.
PACE_DROP_THRESHOLD = 3.0  # seconds

# A car whose last lap is this much slower than the class average is flagged.
CLASS_AVG_THRESHOLD = 5.0  # seconds

# Minimum laps before we consider a car's data reliable.
MIN_LAPS_FOR_ANALYSIS = 2


def detect_anomalies(entries: list[dict]) -> list[dict]:
    """
    Analyze current timing data and return a list of anomaly alerts.

    Each alert is a dict with:
        - car_number: str
        - class_name: str
        - alert_type: str  ("pace_drop", "off_class_pace", "in_pit")
        - severity: str    ("warning", "critical")
        - message: str     (human-readable description)

    Args:
        entries: List of normalized car entries.

    Returns:
        List of alert dicts, sorted by severity (critical first).
    """
    alerts = []

    # Pre-compute class average lap times for comparison
    class_avg = _compute_class_averages(entries)

    for car in entries:
        car_num = car.get("car_number", "?")
        cls = car.get("class_name", "?")
        last_lap = car.get("last_lap_time")
        best_lap = car.get("best_lap_time")
        laps = car.get("laps_completed") or 0
        pit_status = car.get("pit_status")

        # Skip cars with insufficient data
        if laps < MIN_LAPS_FOR_ANALYSIS:
            continue

        # ── Check 1: Pace drop vs own best lap ────────────────────
        if last_lap and best_lap and best_lap > 0:
            drop = last_lap - best_lap
            if drop > PACE_DROP_THRESHOLD:
                severity = "critical" if drop > PACE_DROP_THRESHOLD * 2 else "warning"
                alerts.append({
                    "car_number": car_num,
                    "class_name": cls,
                    "alert_type": "pace_drop",
                    "severity": severity,
                    "message": (
                        f"Car #{car_num} lost significant pace: "
                        f"last lap {last_lap:.3f}s vs best {best_lap:.3f}s "
                        f"(+{drop:.1f}s slower)"
                    ),
                })

        # ── Check 2: Off class pace ───────────────────────────────
        avg = class_avg.get(cls)
        if last_lap and avg and avg > 0:
            diff = last_lap - avg
            if diff > CLASS_AVG_THRESHOLD:
                alerts.append({
                    "car_number": car_num,
                    "class_name": cls,
                    "alert_type": "off_class_pace",
                    "severity": "warning",
                    "message": (
                        f"Car #{car_num} is off {cls} class pace: "
                        f"last lap {last_lap:.3f}s vs class avg {avg:.3f}s "
                        f"(+{diff:.1f}s)"
                    ),
                })

        # ── Check 3: In pit ───────────────────────────────────────
        if pit_status == "IN_PIT":
            alerts.append({
                "car_number": car_num,
                "class_name": cls,
                "alert_type": "in_pit",
                "severity": "info",
                "message": f"Car #{car_num} ({cls}) is currently in the pits",
            })

    # ── Check 4: Close class battles (gap < 2 seconds) ───────────
    alerts.extend(_detect_close_battles(entries))

    # Sort: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))

    return alerts


def _compute_class_averages(entries: list[dict]) -> dict[str, float]:
    """
    Compute average last-lap time per class (excluding outliers in pit).
    Returns dict mapping class_name → average seconds.
    """
    class_times: dict[str, list[float]] = {}
    for car in entries:
        cls = car.get("class_name", "?")
        last_lap = car.get("last_lap_time")
        pit = car.get("pit_status")
        if last_lap and pit != "IN_PIT":
            class_times.setdefault(cls, []).append(last_lap)

    return {
        cls: sum(times) / len(times)
        for cls, times in class_times.items()
        if times
    }


def _detect_close_battles(entries: list[dict]) -> list[dict]:
    """
    Find cars within the same class that are very close together.
    These are the exciting battles fans want to watch.
    """
    alerts = []

    # Group by class
    by_class: dict[str, list[dict]] = {}
    for car in entries:
        cls = car.get("class_name", "?")
        by_class.setdefault(cls, []).append(car)

    for cls, cars in by_class.items():
        # Sort by class position
        cars.sort(key=lambda x: x.get("class_position") or 9999)

        for i in range(len(cars) - 1):
            ahead = cars[i]
            behind = cars[i + 1]

            gap = parse_gap_to_seconds(behind.get("gap_to_class_leader"))
            gap_ahead = parse_gap_to_seconds(ahead.get("gap_to_class_leader"))

            if gap is not None and gap_ahead is not None:
                interval = gap - gap_ahead
                if 0 < interval < 2.0:
                    alerts.append({
                        "car_number": behind.get("car_number", "?"),
                        "class_name": cls,
                        "alert_type": "close_battle",
                        "severity": "info",
                        "message": (
                            f"BATTLE in {cls}: Car #{behind.get('car_number', '?')} "
                            f"is only {interval:.3f}s behind "
                            f"Car #{ahead.get('car_number', '?')} "
                            f"(P{ahead.get('class_position')}/P{behind.get('class_position')})"
                        ),
                    })

    return alerts
