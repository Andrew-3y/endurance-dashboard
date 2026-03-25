# IMSA Endurance Racing Intelligence Dashboard

A real-time endurance racing dashboard that fetches live IMSA timing data and displays leaderboards, class battles, anomaly alerts, and overtake predictions.

## Features

- **Overall & Class Leaderboards** — Live standings with lap times, gaps, and pit status
- **Anomaly Detection** — Flags sudden pace drops, off-class-pace cars, and close battles
- **Overtake Predictions** — Estimates laps until a faster car catches the car ahead
- **Stint & Pit Tracker** — Current driver, pit stop count, and pit status
- **On-Demand** — Fetches data only when you open the page (no background workers)
- **Adapter Architecture** — Designed so new series (WEC, etc.) can be added without rewriting

## Tech Stack

- Python / Flask
- Pandas
- Jinja2 templates
- Plain CSS (dark theme)
- Gunicorn (production server)

## Quick Start

```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```

## Live Data

The dashboard shows live timing data during active IMSA sessions (practice, qualifying, race). When no session is active, a friendly message is displayed. Check the [IMSA schedule](https://www.imsa.com/events/) for upcoming sessions.

## Deployment

Configured for Render free tier. See `render.yaml` for deployment settings.

## Project Structure

```
├── app.py                  # Flask entry point
├── adapters/
│   ├── base_adapter.py     # Abstract adapter interface
│   └── imsa_adapter.py     # IMSA timing data adapter
├── services/
│   ├── cache.py            # In-memory TTL cache
│   ├── data_normalizer.py  # Validation and grouping
│   ├── anomaly_detector.py # Pace drop and battle detection
│   └── predictor.py        # Overtake and stint analysis
├── templates/
│   └── dashboard.html      # Jinja2 template
├── static/
│   └── style.css           # Dark theme styling
├── requirements.txt
└── render.yaml             # Render deployment config
```

## License

Educational project. Not affiliated with IMSA.
