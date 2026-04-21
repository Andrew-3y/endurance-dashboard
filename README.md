# IMSA Endurance Racing Intelligence Dashboard

A production-ready, real-time web dashboard for IMSA endurance racing data. Built with Python and Flask, it fetches live timing data on demand, performs automated analysis, and presents a clean, dark-themed interface covering every phase of a race weekend — practice, qualifying, and race.

Deployed free on Render. No paid APIs. No background workers. No always-on infrastructure.

---

## Live Demo

Deployed at: [endurance-dashboard.onrender.com](https://endurance-dashboard.onrender.com)

> The Render free tier spins down after 15 minutes of inactivity. First visit after idle takes ~15 seconds to cold start. During an active IMSA session, the dashboard displays live data.

> Recent development added driver-focused views and official IMSA / Al Kamel session enrichment for stronger driver-level analysis.

---

## What It Does

The dashboard auto-detects the current session type and shows the right analysis for each phase of the race weekend.

### Live + History Modes (FastF1-style usability)

The dashboard now supports two operating modes and switches automatically:

- **Live Mode**: If an IMSA session is active, live timing data is fetched and rendered.
- **History Mode**: If live data is unavailable, the app loads the latest stored session from SQLite and renders the same analytics views.
- **Empty-state fallback**: If no live session and no stored sessions are available, the app shows:
  - `"No active race and no stored sessions available"`

Automatic behavior:

1. Try live data first.
2. If live data exists, save/update that session in SQLite.
3. If live data is unavailable, load stored session data.
4. If storage is empty, show fallback message.

Manual behavior:

- A **Stored Session** dropdown allows selecting a specific saved session.
- A **Switch to Live Mode** button allows forcing a live attempt.
- The header shows **Live Mode / History Mode** and **Last updated** timestamp.

### Practice Session
| Section | Description |
|---|---|
| Session Summary | Total cars, classes, laps run, field spread, cars with no time |
| Key Takeaways | Auto-generated insights: fastest car, class leaders, consistency, mileage, tight fields |
| Class Speed Comparison | Fastest time, slowest time, spread, and average per class — side by side |
| Fastest Laps (Top 10) | Overall speed ranking by best lap time |
| Fastest per Class | Top cars in each class with gap to class P1 |
| Pace Trend | Per-car status: IMPROVING / PEAKED / CLOSE / SEARCHING — who might go faster in qualifying |
| Consistency Ranking | Gap between last lap and best lap — shows which teams are dialed in |
| Session Mileage | Laps completed per car — low counts may indicate mechanical issues |
| No Timed Lap | Cars that entered but never set a lap time |

### Qualifying Session
| Section | Description |
|---|---|
| Qualifying Summary | Total cars, qualified, classes, total laps attempted, pole time, field spread, DNQ count |
| Key Takeaways | Overall pole, class poles with grid position, tight battles, field spread, DNQ warnings |
| Pole Position Battles | P1 vs P2 per class with driver names, times, laps used, and gap |
| Battles to Watch | Every pair within 0.3s — overall and within class — highlighted for the race |
| Full Grid — Gap Ladder | Gap to car directly ahead AND to pole for every car on the grid |
| Class Qualifying Results | Per-class grid with class position, overall position, gap to pole, and laps attempted |
| Did Not Qualify | Cars with no qualifying time — expected to start at the back |

### Race Session
| Section | Description |
|---|---|
| Race Alerts & Anomalies | Pace drops, off-class-pace cars, pit status, close battles flagged in real time |
| Overtake Predictions | Gap closing rate analysis — estimated laps until a faster car catches the car ahead |
| Overall Leaderboard | Live standings with lap times, gaps, pit stops, and on-track status |
| Class Leaderboards | Separate standings for GTP, LMP3, GTD Pro, GTD with class gaps |
| Stint & Pit Tracker | Current driver, total pit stops, and pit status per car |

### Driver Analytics
| Section | Description |
|---|---|
| Driver Lens | Driver-first summary cards showing visible drivers, on-track vs in-pit counts, and quickest visible lap |
| Driver Class Leaders | Best current driver reference per class |
| Driver Leaderboard | Driver-focused ranking for practice, qualifying, and race |
| Official Driver Enrichment | When available, driver views are enriched from official Al Kamel session documents rather than only the current car snapshot |

### Historical / Official Session Tools
| Section | Description |
|---|---|
| Official Session Explorer | Matched Al Kamel event/session document inventory exposed directly inside the dashboard |
| Race Lineup Support | Race sessions can use official grid documents to show lineup and starting-driver context when full race time cards are not yet available |

### Official Source Intelligence
| Section | Description |
|---|---|
| Official IMSA Sources | Direct links to the live timing app, historical results portal, matched event page, and official session JSON exports |
| Al Kamel Live Feed | Live IMSA feed metadata pulled from the Al Kamel timing service, including feed status and published session schedule |

---

## Architecture

The system uses an **adapter pattern** so that new racing series can be added without modifying any existing code.

```
Browser Request
      │
      ▼
  Flask Route (app.py)
      │
      ├─ Cache hit? → Return cached data
      │
      └─ Cache miss → IMSAAdapter.get_data()
                            │
                            ├─ fetch_raw_data()   → scoring.imsa.com (public JSON)
                            ├─ parse_data()        → extract car entries
                            └─ normalize_data()    → unified schema
                                    │
                                    ├─ session_analyzer  → practice / qualifying analysis
                                    ├─ anomaly_detector  → pace drops, battles
                                    ├─ predictor         → overtake estimates, stints
                                    ├─ driver_analyzer   → driver-centric views
                                    ├─ alkamel_live      → live IMSA feed metadata via Al Kamel WebSocket
                                    ├─ alkamel_results   → official IMSA results/time-card enrichment
                                    └─ data_normalizer   → grouping, formatting
                                    │
                                    ▼
                              Jinja2 Template → HTML Response
```

### Persistence Layer (SQLite)

Live snapshots are persisted to SQLite so the dashboard remains usable after sessions end.

- Storage module: `services/storage.py`
- Default database file: `dashboard.sqlite` (repo root)
- Optional override via env var: `DASHBOARD_DB_PATH`

Storage functions integrated into `app.py`:

- `list_available_sessions()`
- `load_session_data(session_id)`
- `get_latest_session()`
- `save_session_data(series, entries)` (used after successful live fetch)

### Official IMSA Results Enrichment

The dashboard can now enrich IMSA sessions using official Al Kamel sources:

- `https://imsa.results.alkamelcloud.com/`
- `https://livetiming.alkamelsystems.com/imsa`

The Al Kamel results site exposes structured session exports such as:

- `Session Results JSON`
- `Time Cards JSON`

Time cards include lap records tagged by `driver_number`, which allows the dashboard to compute true per-driver session metrics when a matching event/session is available.

For matched historical events, the dashboard also exposes the broader Al Kamel session document inventory so you can browse official PDFs, CSVs, and JSON exports directly from the current event context.

The live timing app also exposes a Meteor / DDP feed. The dashboard now uses that live connection for additional metadata such as:

- whether the IMSA live feed is currently running
- the feed's published session count
- live session schedule documents exposed by the service
- the live feed's official results URL and next-session message

### Adding a New Series (e.g. WEC)
1. Create `adapters/wec_adapter.py` implementing `BaseAdapter`
2. Add one line in `app.py`: `ADAPTERS["wec"] = WECAdapter()`
3. Visit `/wec` — all analysis and UI works automatically

---

## Project Structure

```
endurance-dashboard/
├── app.py                        # Flask entry point, route handling, adapter registry
├── adapters/
│   ├── base_adapter.py           # Abstract interface all adapters must implement
│   └── imsa_adapter.py           # IMSA timing data fetcher and field mapper
├── services/
│   ├── cache.py                  # In-memory TTL cache (default 10s)
│   ├── storage.py                # SQLite persistence for saved sessions/history mode
│   ├── data_normalizer.py        # Schema validation, grouping, lap time formatting
│   ├── session_analyzer.py       # Practice and qualifying specific analysis
│   ├── anomaly_detector.py       # Pace drop, off-pace, and close battle detection
│   ├── predictor.py              # Overtake prediction and stint tracking
│   ├── driver_analyzer.py        # Driver-first analytics and summary views
│   ├── alkamel_live.py           # Live Al Kamel feed metadata client
│   └── alkamel_results.py        # Official Al Kamel session/time-card enrichment
├── templates/
│   └── dashboard.html            # Jinja2 template — adapts layout to session type
├── static/
│   └── style.css                 # Dark theme, class badges, responsive layout
├── requirements.txt
├── render.yaml                   # Render free-tier deployment config
└── .gitignore
```

---

## Normalized Data Schema

Every adapter — regardless of series — must output entries conforming to this schema. This is what makes all downstream services series-agnostic.

| Field | Type | Description |
|---|---|---|
| `series` | str | `"IMSA"`, `"WEC"`, etc. |
| `event_name` | str | e.g. `"Rolex 24 At Daytona"` |
| `session_name` | str | e.g. `"Race"`, `"Practice 1"` |
| `car_number` | str | e.g. `"10"`, `"01"` |
| `team_name` | str | Full team name |
| `class_name` | str | `"GTP"`, `"LMP3"`, `"GTD"`, `"GTD Pro"` |
| `current_driver` | str | Driver currently in the car |
| `overall_position` | int | Position in overall standings |
| `class_position` | int | Position within class |
| `laps_completed` | int | Total laps completed |
| `gap_to_leader` | str/float | Gap to overall leader |
| `gap_to_class_leader` | str/float | Gap to class leader |
| `last_lap_time` | float | Last lap in seconds |
| `best_lap_time` | float | Best lap in seconds |
| `pit_status` | str | `"IN_PIT"` or `"ON_TRACK"` |
| `pit_stops` | int | Total pit stops taken |
| `timestamp` | str | ISO-8601 snapshot time |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Python 3.11 / Flask 3.x |
| Data processing | Native Python services |
| Templates | Jinja2 |
| Styling | Plain CSS (dark theme, no frameworks) |
| Live transport client | `websocket-client` |
| Production server | Gunicorn |
| Hosting | Render free tier |
| Data source | IMSA public scoring API (`scoring.imsa.com`) + official IMSA / Al Kamel results documents |

---

## Local Development

**Requirements:** Python 3.10+

```bash
# Clone the repo
git clone https://github.com/Andrew-3y/endurance-dashboard.git
cd endurance-dashboard

# Install dependencies
pip install -r requirements.txt

# Run the development server
python app.py

# Open in browser
http://localhost:5000
```

The app will show a "No Live Data" message when no IMSA session is active. Check the [IMSA schedule](https://www.imsa.com/events/) for upcoming sessions.

With persisted storage enabled, the app will automatically load the latest stored session in History Mode when no live session is active.

---

## Deployment on Render

### First-time setup

1. Fork or push this repository to your GitHub account
2. Go to [render.com](https://render.com) and sign up with GitHub (free)
3. Click **New → Web Service**
4. Connect your GitHub repository
5. Render auto-detects `render.yaml` — verify these settings:

| Setting | Value |
|---|---|
| Runtime | Python |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 30` |
| Plan | Free |

6. Click **Deploy**

No environment variables required.

### Free tier behaviour

- Spins down after **15 minutes of inactivity**
- Cold start on first request after idle: ~15–20 seconds
- This is intentional — the app is designed for on-demand use, not always-on

---

## Data Source

IMSA publishes live timing data via publicly accessible JSON endpoints at `scoring.imsa.com` during active sessions. This data is served to every browser that visits the official timing page — this app simply reads the same feed.

**Responsible usage:**
- Data is fetched once per page load
- A 10-second in-memory cache prevents repeated calls on quick refreshes
- A polite `User-Agent` header identifies the request
- No scraping loops, no background polling

To find the endpoints yourself: open [imsa.com/scoring](https://www.imsa.com/scoring/) during a live session, open browser DevTools (F12), go to the Network tab, filter by XHR/Fetch, and look for requests returning JSON.

### Official Results Documents

The dashboard also uses official IMSA / Al Kamel result exports when available for driver-level enrichment.

- Results portal: [imsa.results.alkamelcloud.com](https://imsa.results.alkamelcloud.com/)
- Live timing portal: [livetiming.alkamelsystems.com/imsa](https://livetiming.alkamelsystems.com/imsa)

This allows the app to attach official `Results JSON` and `Time Cards JSON` data to the dashboard and improve driver-specific views beyond the live car snapshot alone.

### Official Live Timing Feed

The dashboard also pulls additional IMSA live metadata from the Al Kamel live timing service:

- live feed availability
- published session schedule
- next-session messaging exposed by the service
- feed-level metadata tied to the official IMSA live timing app

This means both official Al Kamel links now contribute data:

- the results portal for historical / document-based enrichment
- the live timing service for live feed metadata

---

## How to Test With Live Data

1. Check the [IMSA Events Calendar](https://www.imsa.com/events/) for an upcoming session
2. Any session works — practice, qualifying, or race
3. Open the dashboard during the session
4. The adapter fetches live data and the appropriate analysis view renders automatically

---

## Disclaimer

This is an independent educational project. Not affiliated with, endorsed by, or connected to IMSA (International Motor Sports Association) or Al Kamel Systems. All timing data is sourced from publicly accessible endpoints and published result documents.

---

## License

This project is licensed under the [MIT License](LICENSE).
