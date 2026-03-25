"""
session_analyzer.py — Session-type detection and session-specific analysis.

WHY THIS EXISTS:
    Practice, qualifying, and race sessions each tell a different story.

    PRACTICE:  Who's fast? Who's consistent? Who ran the most laps?
               Which teams look strong heading into qualifying/race?

    QUALIFYING: Who's on pole? How tight is the grid? Where are the battles?
                What's the starting order for the race?

    RACE:       Covered by anomaly_detector.py and predictor.py.

    This service detects which type of session the data is from and runs
    the appropriate analysis so the UI can show relevant information
    even if you missed the session live.
"""

import logging
import statistics

from services.data_normalizer import format_lap_time

logger = logging.getLogger(__name__)


# ─── Session Type Detection ────────────────────────────────────────────

def detect_session_type(session_name: str) -> str:
    """
    Determine the session type from the session name string.

    IMSA uses names like:
        "Practice 1", "Free Practice 2", "FP1"
        "Qualifying", "Qual", "Q1"
        "Race", "Rolex 24", "Petit Le Mans"

    Returns: "practice", "qualifying", or "race"
    """
    if not session_name:
        return "race"

    name = session_name.lower().strip()

    practice_keywords = ["practice", "fp1", "fp2", "fp3", "fp4", "warm up",
                         "warmup", "warm-up", "free practice", "test"]
    qualifying_keywords = ["qualifying", "qual", "q1", "q2", "q3",
                           "pole", "grid"]

    for kw in practice_keywords:
        if kw in name:
            return "practice"

    for kw in qualifying_keywords:
        if kw in name:
            return "qualifying"

    return "race"


# ═══════════════════════════════════════════════════════════════════════
# PRACTICE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def analyze_practice(entries: list[dict]) -> dict:
    """
    Full practice session analysis.

    Produces:
        - fastest_overall:    Top 10 overall by best lap
        - class_fastest:      Top cars per class by best lap
        - class_summary:      One row per class: best time, spread, car count
        - consistency:        Best-to-last gap ranking (smaller = more dialed in)
        - improvement:        Whether each car is still finding speed or peaked
        - mileage:            Laps completed per car
        - no_time_cars:       Cars that entered but never set a lap time
        - session_stats:      Total cars, total laps, class count, etc.
        - insights:           Human-readable key takeaways
    """
    if not entries:
        return _empty_practice()

    with_best = [e for e in entries if e.get("best_lap_time")]
    with_best.sort(key=lambda x: x["best_lap_time"])

    # ── Fastest overall ───────────────────────────────────────────
    fastest_overall = with_best[:10]

    # ── Fastest per class ─────────────────────────────────────────
    class_fastest: dict[str, list[dict]] = {}
    for e in with_best:
        cls = e.get("class_name", "Unknown")
        class_fastest.setdefault(cls, []).append(e)

    # ── Class summary (one row per class) ─────────────────────────
    class_summary = _build_class_summary(entries, class_fastest)

    # ── Consistency ranking ───────────────────────────────────────
    consistency = _build_consistency(entries)

    # ── Improvement tracker ───────────────────────────────────────
    improvement = _build_improvement(entries)

    # ── Mileage ranking ───────────────────────────────────────────
    mileage = sorted(entries, key=lambda x: x.get("laps_completed", 0), reverse=True)

    # ── Cars with no time set ─────────────────────────────────────
    no_time_cars = [e for e in entries if not e.get("best_lap_time")]

    # ── Session stats ─────────────────────────────────────────────
    session_stats = _build_practice_stats(entries, with_best, class_fastest)

    # ── Insights ──────────────────────────────────────────────────
    insights = _generate_practice_insights(
        entries, fastest_overall, consistency, mileage,
        no_time_cars, class_summary, improvement
    )

    return {
        "fastest_overall": fastest_overall,
        "class_fastest": class_fastest,
        "class_summary": class_summary,
        "consistency": consistency,
        "improvement": improvement[:20],
        "mileage": mileage,
        "no_time_cars": no_time_cars,
        "session_stats": session_stats,
        "insights": insights,
    }


def _empty_practice() -> dict:
    return {
        "fastest_overall": [], "class_fastest": {}, "class_summary": [],
        "consistency": [], "improvement": [], "mileage": [],
        "no_time_cars": [], "session_stats": {}, "insights": [],
    }


def _build_class_summary(entries: list[dict], class_fastest: dict) -> list[dict]:
    """
    One row per class showing: class name, fastest time, slowest time,
    pace spread, number of cars, average best lap.
    Helps you see which classes are tight and which have a runaway leader.
    """
    summary = []
    for cls, cars in class_fastest.items():
        times = [c["best_lap_time"] for c in cars if c.get("best_lap_time")]
        all_in_class = [e for e in entries if e.get("class_name") == cls]
        if not times:
            continue
        fastest = min(times)
        slowest = max(times)
        spread = round(slowest - fastest, 3)
        avg = round(statistics.mean(times), 3)
        summary.append({
            "class_name": cls,
            "car_count": len(all_in_class),
            "cars_with_time": len(times),
            "fastest_time": fastest,
            "slowest_time": slowest,
            "spread": spread,
            "average_time": avg,
            "fastest_car": cars[0].get("car_number", "?") if cars else "?",
            "fastest_team": cars[0].get("team_name", "?") if cars else "?",
        })
    summary.sort(key=lambda x: x["fastest_time"])
    return summary


def _build_consistency(entries: list[dict]) -> list[dict]:
    """
    Gap between each car's last lap and their best lap.
    Small gap = car is dialed in, driver is confident, setup is working.
    Large gap = still searching for pace, or traffic/issues on last run.
    """
    consistency = []
    for e in entries:
        best = e.get("best_lap_time")
        last = e.get("last_lap_time")
        if best and last and best > 0:
            gap = last - best
            pct = (gap / best) * 100  # percentage off best
            consistency.append({
                "car_number": e.get("car_number", "?"),
                "class_name": e.get("class_name", "?"),
                "team_name": e.get("team_name", "?"),
                "current_driver": e.get("current_driver", "?"),
                "best_lap_time": best,
                "last_lap_time": last,
                "consistency_gap": round(gap, 3),
                "pct_off_best": round(pct, 2),
            })
    consistency.sort(key=lambda x: x["consistency_gap"])
    return consistency


def _build_improvement(entries: list[dict]) -> list[dict]:
    """
    For each car, determine if they're still finding time or have plateaued.

    Logic:
        - If last_lap is within 0.3s of best_lap → "peaked" (found their limit)
        - If last_lap is 0.3-1.0s off best → "close" (nearly there)
        - If last_lap is >1.0s off best → "searching" (still working on setup)
        - If last_lap is FASTER than best (shouldn't happen in clean data,
          but could mean the best_lap field isn't the true best) → "improving"

    This helps predict who might go faster in qualifying.
    """
    result = []
    for e in entries:
        best = e.get("best_lap_time")
        last = e.get("last_lap_time")
        if not best or not last:
            continue
        diff = last - best
        if diff <= 0:
            status = "improving"
        elif diff <= 0.3:
            status = "peaked"
        elif diff <= 1.0:
            status = "close"
        else:
            status = "searching"

        result.append({
            "car_number": e.get("car_number", "?"),
            "class_name": e.get("class_name", "?"),
            "team_name": e.get("team_name", "?"),
            "current_driver": e.get("current_driver", "?"),
            "best_lap_time": best,
            "last_lap_time": last,
            "diff": round(diff, 3),
            "status": status,
            "laps_completed": e.get("laps_completed", 0),
        })
    result.sort(key=lambda x: x["best_lap_time"])
    return result


def _build_practice_stats(entries, with_best, class_fastest) -> dict:
    """Session-wide statistics for the summary card."""
    total_laps = sum(e.get("laps_completed", 0) for e in entries)
    laps_list = [e.get("laps_completed", 0) for e in entries if e.get("laps_completed", 0) > 0]
    times = [e["best_lap_time"] for e in with_best]

    return {
        "total_cars": len(entries),
        "cars_with_time": len(with_best),
        "cars_no_time": len(entries) - len(with_best),
        "total_classes": len(class_fastest),
        "total_laps": total_laps,
        "avg_laps_per_car": round(total_laps / len(entries), 1) if entries else 0,
        "median_laps": round(statistics.median(laps_list), 0) if laps_list else 0,
        "fastest_time": min(times) if times else None,
        "slowest_time": max(times) if times else None,
        "overall_spread": round(max(times) - min(times), 3) if len(times) >= 2 else 0,
    }


def _generate_practice_insights(entries, fastest, consistency, mileage,
                                 no_time_cars, class_summary, improvement) -> list[dict]:
    """Generate human-readable insights from practice data."""
    insights = []

    # Fastest car
    if fastest:
        car = fastest[0]
        insights.append({
            "type": "speed",
            "message": (
                f"Fastest in session: Car #{car.get('car_number')} "
                f"({car.get('class_name')}, {car.get('team_name')}) "
                f"set a {format_lap_time(car.get('best_lap_time'))}"
            ),
        })

    # Class fastest summary
    for cs in class_summary:
        insights.append({
            "type": "class",
            "message": (
                f"{cs['class_name']} led by Car #{cs['fastest_car']} "
                f"({cs['fastest_team']}) at {format_lap_time(cs['fastest_time'])} "
                f"— class spread: {cs['spread']:.3f}s across {cs['cars_with_time']} cars"
            ),
        })

    # Most consistent
    if consistency:
        car = consistency[0]
        insights.append({
            "type": "consistency",
            "message": (
                f"Most consistent: Car #{car['car_number']} "
                f"({car['class_name']}) — only {car['consistency_gap']:.3f}s "
                f"({car['pct_off_best']:.1f}%) off their best on the last run"
            ),
        })

    # Most mileage
    if mileage:
        car = mileage[0]
        laps = car.get("laps_completed", 0)
        insights.append({
            "type": "mileage",
            "message": (
                f"Most running: Car #{car.get('car_number')} "
                f"({car.get('class_name')}, {car.get('team_name')}) "
                f"completed {laps} laps"
            ),
        })

    # Cars still improving (could go faster in quali)
    still_improving = [i for i in improvement if i["status"] == "improving"]
    if still_improving:
        nums = ", ".join(f"#{c['car_number']}" for c in still_improving[:5])
        insights.append({
            "type": "trend",
            "message": (
                f"Still finding speed on final runs: {nums} "
                f"— watch for these in qualifying"
            ),
        })

    # Tight classes (spread < 1 second)
    for cs in class_summary:
        if cs["spread"] < 1.0 and cs["cars_with_time"] >= 3:
            insights.append({
                "type": "battle",
                "message": (
                    f"Tight {cs['class_name']} field: only {cs['spread']:.3f}s "
                    f"covers {cs['cars_with_time']} cars — expect close racing"
                ),
            })

    # Cars with no time (potential issues)
    if no_time_cars:
        nums = ", ".join(f"#{c.get('car_number', '?')}" for c in no_time_cars)
        insights.append({
            "type": "warning",
            "message": (
                f"No time set: {nums} — "
                f"did not complete a timed lap (mechanical issue? late arrival?)"
            ),
        })

    # Low mileage warnings
    if mileage and entries:
        avg_laps = sum(e.get("laps_completed", 0) for e in entries) / len(entries)
        low_runners = []
        for car in entries:
            laps = car.get("laps_completed", 0)
            if 0 < laps < avg_laps * 0.3:
                low_runners.append(car)
        if low_runners:
            for car in low_runners[:5]:
                insights.append({
                    "type": "warning",
                    "message": (
                        f"Low running: Car #{car.get('car_number')} "
                        f"({car.get('class_name')}) only completed "
                        f"{car.get('laps_completed', 0)} laps "
                        f"(session avg: {avg_laps:.0f}) — possible issues"
                    ),
                })

    return insights


# ═══════════════════════════════════════════════════════════════════════
# QUALIFYING ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def analyze_qualifying(entries: list[dict]) -> dict:
    """
    Full qualifying session analysis.

    Produces:
        - grid:              Full starting grid sorted by position
        - class_poles:       Pole sitter for each class
        - class_grids:       Per-class grids
        - pole_battles:      P1 vs P2 gap per class
        - gap_ladder:        Gap to car directly ahead for every car
        - no_time_cars:      Cars that didn't set a qualifying time (DNQ)
        - session_stats:     Total cars, spread, laps attempted, etc.
        - tight_battles:     Every position pair where gap < 0.3s
        - insights:          Human-readable key takeaways
    """
    if not entries:
        return _empty_qualifying()

    # ── Build grid ────────────────────────────────────────────────
    grid = sorted(entries, key=lambda x: x.get("overall_position") or 9999)

    # ── Separate no-time cars ─────────────────────────────────────
    no_time_cars = [e for e in entries if not e.get("best_lap_time")]

    # ── Class structures ──────────────────────────────────────────
    class_poles: dict[str, dict] = {}
    class_grids: dict[str, list[dict]] = {}
    for e in grid:
        cls = e.get("class_name", "Unknown")
        class_grids.setdefault(cls, []).append(e)
        if cls not in class_poles and e.get("best_lap_time"):
            class_poles[cls] = e

    # ── Pole battles (P1 vs P2 per class) ─────────────────────────
    pole_battles = _build_pole_battles(class_grids)

    # ── Gap ladder (gap to car directly ahead) ────────────────────
    gap_ladder = _build_gap_ladder(grid)

    # ── Tight battles at every position ───────────────────────────
    tight_battles = _find_tight_battles(grid, class_grids)

    # ── Session stats ─────────────────────────────────────────────
    session_stats = _build_qualifying_stats(entries, grid, class_grids)

    # ── Insights ──────────────────────────────────────────────────
    insights = _generate_qualifying_insights(
        grid, class_poles, pole_battles, no_time_cars,
        tight_battles, class_grids, session_stats
    )

    return {
        "grid": grid,
        "class_poles": class_poles,
        "class_grids": class_grids,
        "pole_battles": pole_battles,
        "gap_ladder": gap_ladder,
        "no_time_cars": no_time_cars,
        "session_stats": session_stats,
        "tight_battles": tight_battles,
        "insights": insights,
    }


def _empty_qualifying() -> dict:
    return {
        "grid": [], "class_poles": {}, "class_grids": {},
        "pole_battles": [], "gap_ladder": [], "no_time_cars": [],
        "session_stats": {}, "tight_battles": [], "insights": [],
    }


def _build_pole_battles(class_grids: dict) -> list[dict]:
    """Compare P1 vs P2 in each class."""
    battles = []
    for cls, cars in class_grids.items():
        timed = [c for c in cars if c.get("best_lap_time")]
        if len(timed) >= 2:
            p1, p2 = timed[0], timed[1]
            gap = p2["best_lap_time"] - p1["best_lap_time"]
            battles.append({
                "class_name": cls,
                "pole_car": p1.get("car_number", "?"),
                "pole_team": p1.get("team_name", "?"),
                "pole_driver": p1.get("current_driver", "?"),
                "pole_time": p1["best_lap_time"],
                "pole_laps": p1.get("laps_completed", 0),
                "second_car": p2.get("car_number", "?"),
                "second_team": p2.get("team_name", "?"),
                "second_driver": p2.get("current_driver", "?"),
                "second_time": p2["best_lap_time"],
                "gap": round(gap, 3),
                "close": gap < 0.2,
            })
    battles.sort(key=lambda x: x["gap"])
    return battles


def _build_gap_ladder(grid: list[dict]) -> list[dict]:
    """
    For every car, compute the gap to the car directly ahead of them.
    This shows WHERE the field is bunched together and where there are
    big gaps. Much more useful than just "gap to pole".
    """
    ladder = []
    for i, car in enumerate(grid):
        car_time = car.get("best_lap_time")
        if i == 0:
            ladder.append({
                "position": car.get("overall_position") or 1,
                "car_number": car.get("car_number", "?"),
                "class_name": car.get("class_name", "?"),
                "team_name": car.get("team_name", "?"),
                "current_driver": car.get("current_driver", "?"),
                "best_lap_time": car_time,
                "gap_to_ahead": None,
                "gap_to_pole": None,
                "laps_completed": car.get("laps_completed", 0),
            })
            continue

        ahead_time = grid[i - 1].get("best_lap_time")
        pole_time = grid[0].get("best_lap_time")

        gap_ahead = None
        gap_pole = None
        if car_time and ahead_time:
            gap_ahead = round(car_time - ahead_time, 3)
        if car_time and pole_time:
            gap_pole = round(car_time - pole_time, 3)

        ladder.append({
            "position": car.get("overall_position") or (i + 1),
            "car_number": car.get("car_number", "?"),
            "class_name": car.get("class_name", "?"),
            "team_name": car.get("team_name", "?"),
            "current_driver": car.get("current_driver", "?"),
            "best_lap_time": car_time,
            "gap_to_ahead": gap_ahead,
            "gap_to_pole": gap_pole,
            "laps_completed": car.get("laps_completed", 0),
        })
    return ladder


def _find_tight_battles(grid: list[dict], class_grids: dict) -> list[dict]:
    """
    Find every pair of consecutive cars (overall AND within class) where
    the gap is under 0.3 seconds. These are the battles to watch.
    """
    battles = []
    seen = set()  # avoid duplicate battle reports

    # Overall tight battles
    for i in range(len(grid) - 1):
        a = grid[i]
        b = grid[i + 1]
        t_a = a.get("best_lap_time")
        t_b = b.get("best_lap_time")
        if t_a and t_b:
            gap = t_b - t_a
            if 0 <= gap < 0.3:
                key = (a.get("car_number"), b.get("car_number"))
                if key not in seen:
                    seen.add(key)
                    battles.append({
                        "scope": "overall",
                        "pos_ahead": a.get("overall_position") or (i + 1),
                        "pos_behind": b.get("overall_position") or (i + 2),
                        "car_ahead": a.get("car_number", "?"),
                        "car_behind": b.get("car_number", "?"),
                        "class_ahead": a.get("class_name", "?"),
                        "class_behind": b.get("class_name", "?"),
                        "gap": round(gap, 3),
                    })

    # Within-class tight battles
    for cls, cars in class_grids.items():
        timed = [c for c in cars if c.get("best_lap_time")]
        for i in range(len(timed) - 1):
            a = timed[i]
            b = timed[i + 1]
            gap = b["best_lap_time"] - a["best_lap_time"]
            if 0 <= gap < 0.3:
                key = (a.get("car_number"), b.get("car_number"))
                if key not in seen:
                    seen.add(key)
                    battles.append({
                        "scope": cls,
                        "pos_ahead": i + 1,
                        "pos_behind": i + 2,
                        "car_ahead": a.get("car_number", "?"),
                        "car_behind": b.get("car_number", "?"),
                        "class_ahead": cls,
                        "class_behind": cls,
                        "gap": round(gap, 3),
                    })

    battles.sort(key=lambda x: x["gap"])
    return battles


def _build_qualifying_stats(entries, grid, class_grids) -> dict:
    """Session-wide qualifying statistics."""
    timed = [e for e in entries if e.get("best_lap_time")]
    times = [e["best_lap_time"] for e in timed]
    total_laps = sum(e.get("laps_completed", 0) for e in entries)

    return {
        "total_cars": len(entries),
        "cars_with_time": len(timed),
        "cars_no_time": len(entries) - len(timed),
        "total_classes": len(class_grids),
        "total_laps_attempted": total_laps,
        "avg_laps_per_car": round(total_laps / len(entries), 1) if entries else 0,
        "fastest_time": min(times) if times else None,
        "slowest_time": max(times) if times else None,
        "field_spread": round(max(times) - min(times), 3) if len(times) >= 2 else 0,
    }


def _generate_qualifying_insights(grid, class_poles, pole_battles, no_time_cars,
                                   tight_battles, class_grids, session_stats) -> list[dict]:
    """Generate human-readable insights from qualifying data."""
    insights = []

    # Overall pole
    if grid:
        pole = grid[0]
        insights.append({
            "type": "pole",
            "message": (
                f"Overall pole: Car #{pole.get('car_number')} "
                f"({pole.get('class_name')}, {pole.get('team_name')}) "
                f"set a {format_lap_time(pole.get('best_lap_time'))}"
            ),
        })

    # Class poles
    for cls, car in class_poles.items():
        overall_pos = car.get("overall_position", "?")
        insights.append({
            "type": "class_pole",
            "message": (
                f"{cls} pole: Car #{car.get('car_number')} "
                f"({car.get('team_name')}) — "
                f"{format_lap_time(car.get('best_lap_time'))} "
                f"(overall grid P{overall_pos})"
            ),
        })

    # Tight pole battles
    for battle in pole_battles:
        if battle["close"]:
            insights.append({
                "type": "battle",
                "message": (
                    f"Tight {battle['class_name']} pole battle: "
                    f"Car #{battle['pole_car']} beat "
                    f"Car #{battle['second_car']} by just {battle['gap']:.3f}s"
                ),
            })

    # Number of tight battles overall
    if tight_battles:
        insights.append({
            "type": "battle",
            "message": (
                f"{len(tight_battles)} qualifying battles within 0.3s — "
                f"expect close racing from the start"
            ),
        })

    # Field spread
    if session_stats.get("field_spread"):
        insights.append({
            "type": "stats",
            "message": (
                f"Field spread: {session_stats['field_spread']:.3f}s covers "
                f"{session_stats['cars_with_time']} cars across "
                f"{session_stats['total_classes']} classes"
            ),
        })

    # DNQ / no time
    if no_time_cars:
        nums = ", ".join(f"#{c.get('car_number', '?')}" for c in no_time_cars)
        insights.append({
            "type": "warning",
            "message": (
                f"Did not qualify / no time: {nums} — "
                f"these cars will likely start at the back of the grid"
            ),
        })

    # Class with the tightest qualifying
    class_spreads = []
    for cls, cars in class_grids.items():
        timed = [c for c in cars if c.get("best_lap_time")]
        if len(timed) >= 2:
            spread = timed[-1]["best_lap_time"] - timed[0]["best_lap_time"]
            class_spreads.append((cls, spread, len(timed)))
    if class_spreads:
        tightest = min(class_spreads, key=lambda x: x[1])
        insights.append({
            "type": "class",
            "message": (
                f"Tightest class: {tightest[0]} — only {tightest[1]:.3f}s "
                f"covers all {tightest[2]} cars"
            ),
        })

    return insights
