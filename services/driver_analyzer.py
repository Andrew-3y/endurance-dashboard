"""
driver_analyzer.py - Driver-centric views built from normalized car entries.

WHY THIS EXISTS:
    The dashboard currently treats each row as a car snapshot. For a useful
    first driver-focused view, we can still project those snapshots into a
    driver lens without changing the storage model yet.

    This service intentionally stays lightweight:
        - one row per currently known driver/car combination
        - session-aware sorting
        - quick summaries for "who is fast / leading / in the pits"

    It does NOT try to claim true per-driver stint attribution across a whole
    race weekend. That will require deeper lap/stint history later.
"""

from __future__ import annotations

from typing import Any


def build_driver_analysis(
    entries: list[dict],
    session_type: str,
    official_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a driver-centric summary and leaderboard for the current session."""
    if not entries and not official_data:
        return _empty_driver_analysis()

    if official_data and official_data.get("drivers"):
        drivers = _build_official_driver_rows(official_data)
        source = "alkamel_results"
    else:
        drivers = _build_snapshot_driver_rows(entries)
        source = "live_snapshot"

    leaderboard = _sort_driver_rows(drivers, session_type)
    class_leaders = _build_class_leaders(leaderboard, session_type)
    insights = _build_driver_insights(leaderboard, class_leaders, session_type, source)
    summary = _build_driver_summary(leaderboard)

    return {
        "source": source,
        "summary": summary,
        "leaderboard": leaderboard,
        "class_leaders": class_leaders,
        "insights": insights,
        "official_links": {
            "page_url": (official_data or {}).get("page_url"),
            "results_json_url": (official_data or {}).get("results_json_url"),
            "time_cards_json_url": (official_data or {}).get("time_cards_json_url"),
        },
    }


def _empty_driver_analysis() -> dict[str, Any]:
    return {
        "source": "none",
        "summary": {},
        "leaderboard": [],
        "class_leaders": [],
        "insights": [],
        "official_links": {},
    }


def _build_snapshot_driver_rows(entries: list[dict]) -> list[dict]:
    drivers = []
    for entry in entries:
        driver_name = entry.get("current_driver") or "Unknown Driver"
        best_lap = entry.get("best_lap_time")
        last_lap = entry.get("last_lap_time")
        diff = None
        if best_lap and last_lap:
            diff = round(last_lap - best_lap, 3)

        drivers.append(
            {
                "driver_name": driver_name,
                "car_number": entry.get("car_number", "?"),
                "team_name": entry.get("team_name", "Unknown Team"),
                "class_name": entry.get("class_name", "Unknown"),
                "overall_position": entry.get("overall_position"),
                "class_position": entry.get("class_position"),
                "best_lap_time": best_lap,
                "last_lap_time": last_lap,
                "lap_delta": diff,
                "avg_valid_lap": None,
                "valid_laps": None,
                "top_speed_kph": None,
                "laps_completed": entry.get("laps_completed", 0),
                "pit_status": entry.get("pit_status", "ON_TRACK"),
                "gap_to_leader": entry.get("gap_to_leader", "--"),
            }
        )
    return drivers


def _build_official_driver_rows(official_data: dict[str, Any]) -> list[dict]:
    rows = []
    for row in official_data.get("drivers", []):
        rows.append(
            {
                "driver_name": row.get("driver_name", "Unknown Driver"),
                "car_number": row.get("car_number", "?"),
                "team_name": row.get("team_name", "Unknown Team"),
                "class_name": row.get("class_name", "Unknown"),
                "overall_position": row.get("overall_position"),
                "class_position": row.get("class_position"),
                "best_lap_time": row.get("best_lap_time"),
                "last_lap_time": None,
                "lap_delta": None,
                "avg_valid_lap": row.get("avg_valid_lap"),
                "valid_laps": row.get("valid_laps"),
                "top_speed_kph": row.get("top_speed_kph"),
                "laps_completed": row.get("laps_completed", 0),
                "pit_status": row.get("pit_status", "ON_TRACK"),
                "gap_to_leader": row.get("gap_to_leader", "--"),
            }
        )
    return rows


def _sort_driver_rows(rows: list[dict], session_type: str) -> list[dict]:
    if session_type == "race":
        return sorted(
            rows,
            key=lambda row: (
                row.get("overall_position") is None,
                row.get("overall_position") or 9999,
                row.get("class_position") or 9999,
            ),
        )

    return sorted(
        rows,
        key=lambda row: (
            row.get("best_lap_time") is None,
            row.get("best_lap_time") or 999999.0,
            row.get("overall_position") or 9999,
        ),
    )


def _build_class_leaders(rows: list[dict], session_type: str) -> list[dict]:
    by_class: dict[str, dict] = {}
    for row in rows:
        cls = row.get("class_name") or "Unknown"
        current = by_class.get(cls)
        if current is None:
            by_class[cls] = row
            continue

        if session_type == "race":
            current_pos = current.get("class_position") or 9999
            row_pos = row.get("class_position") or 9999
            if row_pos < current_pos:
                by_class[cls] = row
            continue

        current_best = current.get("best_lap_time")
        row_best = row.get("best_lap_time")
        if current_best is None and row_best is not None:
            by_class[cls] = row
        elif row_best is not None and current_best is not None and row_best < current_best:
            by_class[cls] = row

    leaders = list(by_class.values())
    if session_type == "race":
        leaders.sort(key=lambda row: row.get("class_position") or 9999)
    else:
        leaders.sort(key=lambda row: row.get("best_lap_time") or 999999.0)
    return leaders


def _build_driver_summary(rows: list[dict]) -> dict[str, Any]:
    on_track = sum(1 for row in rows if row.get("pit_status") != "IN_PIT")
    in_pit = len(rows) - on_track
    timed_rows = [row for row in rows if row.get("best_lap_time")]
    classes = sorted({row.get("class_name", "Unknown") for row in rows})

    return {
        "total_drivers": len(rows),
        "classes_represented": len(classes),
        "drivers_on_track": on_track,
        "drivers_in_pit": in_pit,
        "fastest_driver": timed_rows[0]["driver_name"] if timed_rows else None,
        "fastest_time": timed_rows[0]["best_lap_time"] if timed_rows else None,
    }


def _build_driver_insights(
    rows: list[dict],
    class_leaders: list[dict],
    session_type: str,
    source: str,
) -> list[dict[str, str]]:
    insights: list[dict[str, str]] = []
    if not rows:
        return insights

    timed_rows = [row for row in rows if row.get("best_lap_time")]
    if timed_rows and session_type != "race":
        quickest = timed_rows[0]
        insights.append(
            {
                "type": "speed",
                "message": (
                    f"{quickest['driver_name']} is the quickest named driver currently shown "
                    f"in car #{quickest['car_number']} for {quickest['team_name']}."
                ),
            }
        )
    elif rows and session_type == "race" and source == "alkamel_results":
        front = rows[0]
        insights.append(
            {
                "type": "race",
                "message": (
                    f"Official Al Kamel race driver data is available for car #{front['car_number']} "
                    f"and its lineup is included in the driver view."
                ),
            }
        )

    if source == "alkamel_results":
        insights.append(
            {
                "type": "source",
                "message": "Driver ranking is using official Al Kamel time cards and results JSON for this session.",
            }
        )

    if class_leaders:
        leader_names = ", ".join(
            f"{row['class_name']}: {row['driver_name']}" for row in class_leaders[:4]
        )
        insights.append(
            {
                "type": "class",
                "message": f"Current class reference drivers: {leader_names}.",
            }
        )

    busiest = max(rows, key=lambda row: row.get("laps_completed", 0))
    if busiest.get("laps_completed", 0) > 0:
        insights.append(
            {
                "type": "mileage",
                "message": (
                    f"{busiest['driver_name']} is attached to the highest-mileage visible car "
                    f"(#{busiest['car_number']}, {busiest['laps_completed']} laps)."
                ),
            }
        )

    pit_rows = [row for row in rows if row.get("pit_status") == "IN_PIT"]
    if pit_rows:
        sample = ", ".join(row["driver_name"] for row in pit_rows[:3])
        insights.append(
            {
                "type": "pit",
                "message": f"Drivers currently shown in pit lane include {sample}.",
            }
        )

    return insights
