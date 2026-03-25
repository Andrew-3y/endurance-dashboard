"""
predictor.py — Predicts overtakes and gap closing based on current pace data.

WHY THIS IS USEFUL:
    In endurance racing, battles develop over many laps.  If Car A is 5 seconds
    behind Car B but is 0.5s/lap faster, they'll meet in ~10 laps.  This service
    computes those projections.

LIMITATIONS (HONEST):
    With a single data snapshot, we can only estimate closing rates from the
    difference in BEST lap times (not a rolling average over time).  Real
    closing rates fluctuate due to traffic, fuel load, tire wear, etc.

    Our predictions are ESTIMATES, not guarantees.  We label them clearly.
"""

import logging

from services.data_normalizer import parse_gap_to_seconds

logger = logging.getLogger(__name__)

# If the pace difference is smaller than this, don't predict (noise).
MIN_PACE_DIFF = 0.1  # seconds per lap

# Don't predict overtakes further out than this many laps.
MAX_PREDICTION_LAPS = 50


def predict_overtakes(entries: list[dict]) -> list[dict]:
    """
    For each class, look at consecutive cars and predict when the car
    behind might catch the car ahead, based on best lap time difference.

    Each prediction is a dict with:
        - chaser: str          (car number of the faster car)
        - target: str          (car number of the slower car ahead)
        - class_name: str
        - gap_seconds: float   (current gap)
        - pace_diff: float     (seconds/lap the chaser is faster)
        - laps_to_catch: int   (estimated laps until they meet)
        - message: str         (human-readable prediction)

    Returns:
        List of prediction dicts, sorted by laps_to_catch (soonest first).
    """
    predictions = []

    # Group by class
    by_class: dict[str, list[dict]] = {}
    for car in entries:
        cls = car.get("class_name", "?")
        by_class.setdefault(cls, []).append(car)

    for cls, cars in by_class.items():
        cars.sort(key=lambda x: x.get("class_position") or 9999)

        for i in range(len(cars) - 1):
            ahead = cars[i]
            behind = cars[i + 1]

            # We need both cars to have best lap times
            ahead_best = ahead.get("best_lap_time")
            behind_best = behind.get("best_lap_time")

            if not ahead_best or not behind_best:
                continue

            # Pace difference: positive means the car behind is faster
            pace_diff = ahead_best - behind_best

            if pace_diff < MIN_PACE_DIFF:
                continue  # behind car is not faster, skip

            # Current gap between them
            gap_behind = parse_gap_to_seconds(behind.get("gap_to_class_leader"))
            gap_ahead = parse_gap_to_seconds(ahead.get("gap_to_class_leader"))

            if gap_behind is None or gap_ahead is None:
                continue

            gap = gap_behind - gap_ahead
            if gap <= 0:
                continue  # data inconsistency, skip

            # Estimate laps to catch
            laps_to_catch = gap / pace_diff

            if laps_to_catch > MAX_PREDICTION_LAPS:
                continue  # too far out to be meaningful

            laps_int = int(round(laps_to_catch))

            predictions.append({
                "chaser": behind.get("car_number", "?"),
                "target": ahead.get("car_number", "?"),
                "class_name": cls,
                "gap_seconds": round(gap, 3),
                "pace_diff": round(pace_diff, 3),
                "laps_to_catch": laps_int,
                "message": (
                    f"Car #{behind.get('car_number', '?')} is closing on "
                    f"Car #{ahead.get('car_number', '?')} in {cls}: "
                    f"gap {gap:.3f}s, pace advantage {pace_diff:.3f}s/lap → "
                    f"~{laps_int} laps to catch"
                ),
            })

    predictions.sort(key=lambda p: p["laps_to_catch"])
    return predictions


def compute_stint_info(entries: list[dict]) -> list[dict]:
    """
    Compute basic stint/pit information for each car.

    With a single snapshot, we can report:
        - Current pit status
        - Total pit stops
        - Current driver

    True stint analysis (stint length, lap-by-lap degradation) requires
    historical data.  This function provides what's available now and
    is structured so that history can be added later.

    Returns:
        List of stint summary dicts.
    """
    stints = []
    for car in entries:
        stints.append({
            "car_number": car.get("car_number", "?"),
            "class_name": car.get("class_name", "?"),
            "team_name": car.get("team_name", "?"),
            "current_driver": car.get("current_driver", "Unknown"),
            "pit_status": car.get("pit_status", "ON_TRACK"),
            "pit_stops": car.get("pit_stops", 0),
            "laps_completed": car.get("laps_completed", 0),
        })
    return stints
