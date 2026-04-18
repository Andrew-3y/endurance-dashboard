"""
alkamel_results.py - Driver/session enrichment from IMSA's Al Kamel results site.

WHY THIS EXISTS:
    The current dashboard already has a good live car snapshot, but the
    official Al Kamel results site exposes richer session documents including:
        - session results JSON
        - time cards JSON
        - direct document URLs for the current event/session

    Time cards are especially useful because laps are tagged with a
    driver_number, which lets us build actual per-driver session metrics.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from statistics import mean
from typing import Any
from urllib.parse import quote_plus, unquote, urljoin

import requests

logger = logging.getLogger(__name__)

ALKAMEL_RESULTS_BASE = "https://imsa.results.alkamelcloud.com/"
ALKAMEL_LIVE_URL = "https://livetiming.alkamelsystems.com/imsa"
ALKAMEL_TIMEOUT = 15
CHAMPIONSHIP_SLUG = "imsa weathertech sportscar championship"
STOPWORDS = {
    "the", "of", "at", "grand", "prix", "acura", "motul", "rolex",
    "street", "course", "international", "raceway", "speedway", "circuit",
}


def get_alkamel_session_data(entries: list[dict]) -> dict[str, Any] | None:
    """
    Best-effort fetch of Al Kamel session data matching the dashboard entries.

    Returns None when no reliable event/session match is available.
    """
    if not entries:
        return None

    first = entries[0]
    event_name = str(first.get("event_name") or "")
    session_name = str(first.get("session_name") or "")
    if not event_name or not session_name:
        return None

    season_value = _build_season_value(entries)
    try:
        index_html = _fetch_text(ALKAMEL_RESULTS_BASE)
        event_options = _parse_select_options(index_html)
        event_value = _find_best_event_value(event_name, event_options)
        if not event_value:
            return None

        page_url = f"{ALKAMEL_RESULTS_BASE}?season={quote_plus(season_value)}&evvent={quote_plus(event_value)}"
        page_html = _fetch_text(page_url)
        docs = _extract_session_documents(page_html)
        session_docs = _pick_session_documents(docs, session_name)
        if not session_docs:
            return None

        results_data = None
        time_cards_data = None

        if session_docs.get("results_json_url"):
            results_data = _fetch_json(session_docs["results_json_url"])

        if session_docs.get("time_cards_json_url"):
            time_cards_data = _fetch_json(session_docs["time_cards_json_url"])

        if not results_data and not time_cards_data:
            return None

        driver_rows = _build_driver_rows(results_data, time_cards_data)

        return {
            "page_url": page_url,
            "live_timing_url": ALKAMEL_LIVE_URL,
            "results_json_url": session_docs.get("results_json_url"),
            "time_cards_json_url": session_docs.get("time_cards_json_url"),
            "session": (time_cards_data or results_data or {}).get("session", {}),
            "drivers": driver_rows,
        }
    except Exception:
        logger.exception("Failed loading Al Kamel session data for %s / %s", event_name, session_name)
        return None


def _fetch_text(url: str) -> str:
    response = requests.get(url, timeout=ALKAMEL_TIMEOUT, headers={"User-Agent": "EnduranceDashboard/1.0"})
    response.raise_for_status()
    return response.text


def _fetch_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=ALKAMEL_TIMEOUT, headers={"User-Agent": "EnduranceDashboard/1.0"})
    response.raise_for_status()
    return json.loads(response.content.decode("utf-8-sig"))


def _build_season_value(entries: list[dict]) -> str:
    now_year = datetime.now(timezone.utc).year
    year = now_year
    for entry in entries:
        timestamp = entry.get("timestamp")
        if isinstance(timestamp, str):
            try:
                year = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).year
                break
            except ValueError:
                continue
    return f"{str(year)[-2:]}_{year}"


def _parse_select_options(html: str) -> list[tuple[str, str]]:
    pattern = re.compile(r'<option[^>]*value="([^"]+)"[^>]*>(.*?)</option>', re.I | re.S)
    options = []
    for value, label in pattern.findall(html):
        clean_label = re.sub(r"<[^>]+>", "", label).strip()
        if not value or not clean_label:
            continue
        options.append((value.strip(), clean_label))
    return options


def _find_best_event_value(event_name: str, options: list[tuple[str, str]]) -> str | None:
    normalized_event = _normalized_tokens(event_name)
    best_score = 0.0
    best_value = None

    for value, label in options:
        if "_" not in value:
            continue
        tokens = _normalized_tokens(label)
        if not tokens:
            continue

        overlap = len(normalized_event & tokens)
        if overlap == 0:
            continue

        score = overlap / max(len(tokens), 1)
        if score > best_score:
            best_score = score
            best_value = value

    return best_value


def _normalized_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {word for word in words if word not in STOPWORDS}


def _extract_session_documents(html: str) -> list[dict[str, str]]:
    href_pattern = re.compile(r'href="([^"]+)"', re.I)
    docs = []
    for href in href_pattern.findall(html):
        if not href.startswith("Results/"):
            continue

        decoded = unquote(href)
        normalized = decoded.lower()
        if CHAMPIONSHIP_SLUG not in normalized:
            continue

        parts = decoded.split("/")
        if len(parts) < 6:
            continue

        session_folder = parts[-2]
        filename = parts[-1]
        docs.append(
            {
                "url": urljoin(ALKAMEL_RESULTS_BASE, href),
                "session_folder": session_folder,
                "filename": filename,
                "decoded_path": decoded,
            }
        )
    return docs


def _pick_session_documents(docs: list[dict[str, str]], session_name: str) -> dict[str, str] | None:
    session_key = _normalize_session_name(session_name)
    matching = [doc for doc in docs if _normalize_session_folder(doc["session_folder"]) == session_key]
    if not matching:
        return None

    results_json_url = None
    time_cards_json_url = None
    for doc in matching:
        filename = doc["filename"].lower()
        if filename.endswith(".json") and "time cards" in filename:
            time_cards_json_url = doc["url"]
        elif filename.endswith(".json") and "results" in filename and "class" not in filename:
            results_json_url = doc["url"]

    if not results_json_url and not time_cards_json_url:
        return None

    return {
        "results_json_url": results_json_url,
        "time_cards_json_url": time_cards_json_url,
    }


def _normalize_session_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return " ".join(cleaned.split())


def _normalize_session_folder(folder: str) -> str:
    decoded = unquote(folder)
    label = decoded.split("_", 1)[1] if "_" in decoded else decoded
    return _normalize_session_name(label)


def _build_driver_rows(results_data: dict[str, Any] | None, time_cards_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    classification_by_car: dict[str, dict[str, Any]] = {}
    if results_data:
        for row in results_data.get("classification", []):
            car_number = str(row.get("number") or "").strip()
            if car_number:
                classification_by_car[car_number] = row

    driver_rows: list[dict[str, Any]] = []
    if not time_cards_data:
        return driver_rows

    for participant in time_cards_data.get("participants", []):
        car_number = str(participant.get("number") or "?")
        classification = classification_by_car.get(car_number, {})
        drivers = {
            str(driver.get("number")): driver
            for driver in participant.get("drivers", [])
            if driver.get("number") is not None
        }

        laps_by_driver: dict[str, list[dict[str, Any]]] = {}
        for lap in participant.get("laps", []):
            driver_number = str(lap.get("driver_number") or "").strip()
            if not driver_number:
                continue
            laps_by_driver.setdefault(driver_number, []).append(lap)

        for driver_number, driver in drivers.items():
            driver_laps = laps_by_driver.get(driver_number, [])
            valid_laps = [
                lap for lap in driver_laps
                if lap.get("is_valid") and _parse_lap_time(lap.get("time")) is not None
            ]
            valid_times = [_parse_lap_time(lap.get("time")) for lap in valid_laps]
            valid_times = [time for time in valid_times if time is not None]

            best_lap = min(valid_times) if valid_times else None
            avg_valid_lap = round(mean(valid_times), 3) if valid_times else None
            top_speed = _max_float(lap.get("top_speed_kph") for lap in driver_laps)

            driver_rows.append(
                {
                    "driver_name": _format_driver_name(driver),
                    "driver_number": driver_number,
                    "car_number": car_number,
                    "team_name": participant.get("team") or "Unknown Team",
                    "class_name": participant.get("class") or "Unknown",
                    "vehicle": participant.get("vehicle") or "",
                    "manufacturer": participant.get("manufacturer") or "",
                    "overall_position": _to_int(classification.get("position")),
                    "best_lap_time": best_lap,
                    "avg_valid_lap": avg_valid_lap,
                    "laps_completed": len(driver_laps),
                    "valid_laps": len(valid_laps),
                    "top_speed_kph": top_speed,
                    "pit_stops": _to_int(classification.get("pit_stops")) or 0,
                    "gap_to_leader": classification.get("gap_first") or "--",
                    "pit_status": "ON_TRACK",
                }
            )

    driver_rows.sort(key=lambda row: (row.get("best_lap_time") is None, row.get("best_lap_time") or 999999.0))
    return driver_rows


def _format_driver_name(driver: dict[str, Any]) -> str:
    first = str(driver.get("firstname") or "").strip()
    last = str(driver.get("surname") or "").strip()
    full = f"{first} {last}".strip()
    return full or "Unknown Driver"


def _parse_lap_time(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    text = str(value).strip()
    try:
        if ":" in text:
            minutes, seconds = text.split(":", 1)
            return float(minutes) * 60 + float(seconds)
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _max_float(values: Any) -> float | None:
    parsed = []
    for value in values:
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            continue
    return max(parsed) if parsed else None
