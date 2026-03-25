"""
app.py — Flask application entry point for the Endurance Racing Dashboard.

THIS IS THE MAIN FILE. When a user opens the dashboard in their browser:

    1. Flask receives the HTTP request.
    2. We check the cache — if fresh data exists, use it.
    3. If not, the adapter fetches live data from IMSA.
    4. Data is normalized, analyzed, and predictions are computed.
    5. Everything is passed to the Jinja2 template for rendering.
    6. The user sees a fully rendered HTML page. Done.

NO BACKGROUND WORKERS. NO INFINITE LOOPS. Just request → response.

═══════════════════════════════════════════════════════════════════════════
HOW TO ADD WEC LATER (2-MINUTE JOB):
═══════════════════════════════════════════════════════════════════════════
    1. Create  adapters/wec_adapter.py  (implement BaseAdapter)
    2. In this file, add:
           from adapters.wec_adapter import WECAdapter
           ADAPTERS["wec"] = WECAdapter()
    3. The /wec route will automatically work.
    That's it.  All services (anomaly, prediction) work unchanged.
═══════════════════════════════════════════════════════════════════════════
"""

import logging
import os

from flask import Flask, render_template

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

# ─── Logging Setup ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Flask App ──────────────────────────────────────────────────────────
app = Flask(__name__)

# ─── Adapters Registry ─────────────────────────────────────────────────
# Each series gets an adapter instance and its own cache.
# To add WEC:  ADAPTERS["wec"] = WECAdapter()  — that's literally it.
ADAPTERS = {
    "imsa": IMSAAdapter(),
    # "wec": WECAdapter(),  ← uncomment when WEC adapter is built
}

CACHES = {
    series: SimpleCache(ttl_seconds=10)
    for series in ADAPTERS
}

# Register the lap time formatter so templates can use it
app.jinja_env.filters["lap_time"] = format_lap_time


# ─── Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """
    Default route — shows the IMSA dashboard.
    Redirects to the IMSA series view.
    """
    return dashboard("imsa")


@app.route("/<series>")
def dashboard(series: str):
    """
    Main dashboard route for any series.

    How it works:
        1. Look up the adapter for the requested series.
        2. Check cache. If fresh, use cached data.
        3. Otherwise, fetch fresh data through the adapter.
        4. Run analysis (anomalies, predictions, stints).
        5. Render the HTML template with all the data.

    If anything goes wrong (no adapter, no data, endpoint down),
    we render the same template with an error message instead of crashing.
    """
    series = series.lower()

    # ── Validate series ──────────────────────────────────────────
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
        )

    adapter = ADAPTERS[series]
    cache = CACHES[series]

    # ── Try cache first ──────────────────────────────────────────
    cached = cache.get()
    if cached is not None:
        logger.info("Serving %s data from cache (age: %.1fs)", series, cache.age_seconds)
        return _render_dashboard(cached)

    # ── Fetch fresh data ─────────────────────────────────────────
    try:
        logger.info("Fetching fresh %s data...", series)
        entries = adapter.get_data()
        entries = validate_entries(entries)
        cache.set(entries)
        logger.info("Fetched %d entries for %s", len(entries), series)
        return _render_dashboard(entries)

    except AdapterError as exc:
        logger.warning("Adapter error for %s: %s", series, exc)
        return render_template(
            "dashboard.html",
            error=str(exc),
            event_info={"series": series.upper(), "event_name": "Data Unavailable", "session_name": ""},
            entries=[],
            classes={},
            anomalies=[],
            predictions=[],
            stints=[],
        )

    except Exception as exc:
        logger.exception("Unexpected error for %s", series)
        return render_template(
            "dashboard.html",
            error=f"An unexpected error occurred: {exc}",
            event_info={"series": series.upper(), "event_name": "Error", "session_name": ""},
            entries=[],
            classes={},
            anomalies=[],
            predictions=[],
            stints=[],
        )


def _render_dashboard(entries: list[dict]) -> str:
    """
    Given normalized entries, compute all analytics and render the template.
    Separated into its own function so both cache-hit and fresh-fetch paths
    can use it without duplicating logic.
    """
    event_info = get_event_info(entries)
    classes = group_by_class(entries)
    anomalies = detect_anomalies(entries)
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
    )


@app.route("/health")
def health():
    """Health check endpoint for Render. Returns 200 if the app is alive."""
    return {"status": "ok"}, 200


# ─── Entry Point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
