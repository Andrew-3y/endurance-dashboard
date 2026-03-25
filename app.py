"""
app.py - Flask application entry point for the Endurance Racing Dashboard.

THIS IS THE MAIN FILE. When a user opens the dashboard in their browser:

    1. Flask receives the HTTP request.
    2. We check the cache - if fresh data exists, use it.
    3. If not, the adapter fetches live data from IMSA.
    4. Data is normalized, analyzed, and predictions are computed.
    5. Everything is passed to the Jinja2 template for rendering.
    6. The user sees a fully rendered HTML page. Done.

NO BACKGROUND WORKERS. NO INFINITE LOOPS. Just request -> response.

===============================================================================
HOW TO ADD WEC LATER (2-MINUTE JOB):
===============================================================================
    1. Create  adapters/wec_adapter.py  (implement BaseAdapter)
    2. In this file, add:
           from adapters.wec_adapter import WECAdapter
           ADAPTERS["wec"] = WECAdapter()
    3. The /wec route will automatically work.
    That's it.  All services (anomaly, prediction) work unchanged.
===============================================================================
"""

import logging
import os

from flask import Flask, render_template, request

from adapters.base_adapter import AdapterError
from adapters.imsa_adapter import IMSAAdapter
from services.anomaly_detector import detect_anomalies
from services.cache import SimpleCache
from services.data_normalizer import (
    format_lap_time,
    get_event_info,
    group_by_class,
    validate_entries,
)
from services.predictor import compute_stint_info, predict_overtakes
from services.session_analyzer import analyze_practice, analyze_qualifying
from services.storage import (
    get_latest_session,
    list_available_sessions,
    load_session_data,
    save_session_data,
)

# --- Logging Setup -----------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- Flask App ---------------------------------------------------------------
app = Flask(__name__)

# --- Adapters Registry -------------------------------------------------------
# Each series gets an adapter instance and its own cache.
# To add WEC:  ADAPTERS["wec"] = WECAdapter()  - that's literally it.
ADAPTERS = {
    "imsa": IMSAAdapter(),
    # "wec": WECAdapter(),  <- uncomment when WEC adapter is built
}

CACHES = {
    series: SimpleCache(ttl_seconds=10)
    for series in ADAPTERS
}

# Register the lap time formatter so templates can use it
app.jinja_env.filters["lap_time"] = format_lap_time


def _extract_last_updated(entries: list[dict]) -> str | None:
    """Best-effort latest timestamp from current entries."""
    timestamps = [
        e.get("timestamp")
        for e in entries
        if isinstance(e, dict) and e.get("timestamp")
    ]
    return max(timestamps) if timestamps else None


def _safe_list_available_sessions(series: str) -> list[dict]:
    """Storage listing should never crash the page render."""
    try:
        return list_available_sessions(series=series)
    except Exception:
        logger.exception("Failed listing stored sessions for %s", series)
        return []


def get_live_data(series: str, adapter: IMSAAdapter, cache: SimpleCache) -> tuple[list[dict], str | None]:
    """
    Return live entries when available. Empty list means no active live data.
    Also persists fresh live snapshots into SQLite history.
    """
    # Try cache first
    cached = cache.get()
    if cached is not None:
        logger.info("Serving %s data from cache (age: %.1fs)", series, cache.age_seconds)
        return cached, None

    # Fetch fresh data
    try:
        logger.info("Fetching fresh %s data...", series)
        entries = validate_entries(adapter.get_data())
        if not entries:
            return [], None
        cache.set(entries)
        try:
            save_session_data(series=series, entries=entries)
        except Exception:
            logger.exception("Live data fetched but could not be saved to storage for %s", series)
        logger.info("Fetched %d entries for %s", len(entries), series)
        return entries, None

    except AdapterError as exc:
        logger.info("No live data for %s: %s", series, exc)
        return [], str(exc)

    except Exception as exc:
        logger.exception("Unexpected live fetch error for %s", series)
        return [], f"Live data fetch failed: {exc}"


def get_history_data(series: str, session_id: int | None = None) -> tuple[list[dict], dict | None, str | None]:
    """
    Return entries from storage.
    - If session_id is provided, try that session.
    - Else use latest stored session.
    """
    try:
        session_meta = None

        if session_id is not None:
            sessions = _safe_list_available_sessions(series)
            session_meta = next((s for s in sessions if s.get("session_id") == session_id), None)

        if session_meta is None:
            session_meta = get_latest_session(series=series)

        if not session_meta:
            return [], None, None

        entries = validate_entries(load_session_data(session_meta["session_id"]))
        if not entries:
            return [], session_meta, "Stored session exists but contains no usable data."

        return entries, session_meta, None

    except Exception as exc:
        logger.exception("History load failed for %s", series)
        return [], None, f"History load failed: {exc}"


# --- Routes ------------------------------------------------------------------

@app.route("/")
def index():
    """
    Default route - shows the IMSA dashboard.
    Redirects to the IMSA series view.
    """
    return dashboard("imsa")


@app.route("/<series>")
def dashboard(series: str):
    """
    Main dashboard route for any series.

    Auto mode logic:
        1. If a race/session is active: fetch live data, save it, show Live Mode.
        2. Else if stored sessions exist: load latest or selected session, show History Mode.
        3. Else: show fallback message.

    If anything goes wrong (no adapter, no data, endpoint down),
    we render the same template with an error message instead of crashing.
    """
    series = series.lower()

    # --- Validate series -----------------------------------------------------
    if series not in ADAPTERS:
        available = ", ".join(ADAPTERS.keys())
        return render_template(
            "dashboard.html",
            error=f"Unknown series '{series}'. Available: {available}",
            event_info={"series": "?", "event_name": "Error", "session_name": ""},
            entries=[],
            classes={},
            anomalies=[],
            predictions=[],
            stints=[],
            practice={},
            qualifying={},
            mode="history",
            available_sessions=[],
            selected_session_id=None,
            auto_message=None,
            last_updated=None,
            live_fetch_error=None,
        ), 404

    adapter = ADAPTERS[series]
    cache = CACHES[series]
    requested_session_id = request.args.get("session_id", type=int)
    available_sessions = _safe_list_available_sessions(series)

    # If user manually selects a stored session, honor it first.
    if requested_session_id is not None:
        history_entries, session_meta, history_error = get_history_data(
            series=series,
            session_id=requested_session_id,
        )
        if history_entries:
            return _render_dashboard(
                history_entries,
                mode="history",
                available_sessions=available_sessions,
                selected_session_id=requested_session_id,
                auto_message=None,
                last_updated=(session_meta or {}).get("last_updated") or _extract_last_updated(history_entries),
                live_fetch_error=None,
            )
        requested_error = history_error or "Selected stored session was not found."
    else:
        requested_error = None

    # Auto try live mode first.
    live_entries, live_error = get_live_data(series=series, adapter=adapter, cache=cache)
    if live_entries:
        updated_sessions = _safe_list_available_sessions(series)
        return _render_dashboard(
            live_entries,
            mode="live",
            available_sessions=updated_sessions,
            selected_session_id=None,
            auto_message=None,
            last_updated=_extract_last_updated(live_entries),
            live_fetch_error=None,
        )

    # No live data -> automatic history fallback.
    history_entries, session_meta, history_error = get_history_data(series=series)
    if history_entries:
        return _render_dashboard(
            history_entries,
            mode="history",
            available_sessions=available_sessions,
            selected_session_id=(session_meta or {}).get("session_id"),
            auto_message="No active race. Showing latest stored session.",
            last_updated=(session_meta or {}).get("last_updated") or _extract_last_updated(history_entries),
            live_fetch_error=live_error,
        )

    # No live data and no stored sessions.
    final_error = requested_error or history_error or live_error or "No active race and no stored sessions available"
    return render_template(
        "dashboard.html",
        error=final_error,
        event_info={"series": series.upper(), "event_name": "Data Unavailable", "session_name": ""},
        entries=[],
        classes={},
        anomalies=[],
        predictions=[],
        stints=[],
        practice={},
        qualifying={},
        mode="history",
        available_sessions=available_sessions,
        selected_session_id=requested_session_id,
        auto_message=None,
        last_updated=None,
        live_fetch_error=live_error,
    )


def _render_dashboard(
    entries: list[dict],
    mode: str = "live",
    available_sessions: list[dict] | None = None,
    selected_session_id: int | None = None,
    auto_message: str | None = None,
    last_updated: str | None = None,
    live_fetch_error: str | None = None,
) -> str:
    """
    Given normalized entries, compute all analytics and render the template.
    Separated into its own function so both live and history paths
    can use it without duplicating logic.

    The session_type (practice/qualifying/race) determines which analysis
    is run and which sections the template displays.
    """
    event_info = get_event_info(entries)
    classes = group_by_class(entries)
    session_type = event_info.get("session_type", "race")

    # Always compute these (useful for all session types)
    anomalies = detect_anomalies(entries)

    # Session-specific analysis
    predictions = []
    stints = []
    practice_data = {}
    qualifying_data = {}

    if session_type == "practice":
        practice_data = analyze_practice(entries)
    elif session_type == "qualifying":
        qualifying_data = analyze_qualifying(entries)
    else:  # race
        predictions = predict_overtakes(entries)
        stints = compute_stint_info(entries)

    return render_template(
        "dashboard.html",
        error=None,
        event_info=event_info,
        entries=entries,
        classes=classes,
        anomalies=anomalies,
        predictions=predictions,
        stints=stints,
        practice=practice_data,
        qualifying=qualifying_data,
        mode=mode,
        available_sessions=available_sessions or [],
        selected_session_id=selected_session_id,
        auto_message=auto_message,
        last_updated=last_updated or _extract_last_updated(entries),
        live_fetch_error=live_fetch_error,
    )


@app.route("/health")
def health():
    """Health check endpoint for Render. Returns 200 if the app is alive."""
    return {"status": "ok"}, 200


# --- Entry Point -------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
