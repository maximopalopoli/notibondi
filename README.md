# notibondi

Notibondi is a web app for Buenos Aires buses, useful to find nearby stops,
see when the next buses arrive (live when the city feed has data, scheduled
when it doesn't), and see a line's route and its live buses on a map.

## Features

- **Nearby stops**: the stops around a point, with the lines that stop there.
- **Stop search**: by name ("plaza italia").
- **Arrivals**: the next buses at a stop. Live times from the GCBA real-time
  feed, and the GTFS schedule for lines that have no live data.
- **Lines and routes**: search a line by number ("152" gives 152A, 152B…) and
  see both directions on a map, with arrows that show where each one goes.
- **Live buses**: the line's buses on the same map, colored by direction and
  refreshed every 30 s. A line with no live data says so under the map.

## Stack

| Layer | Tools |
| --- | --- |
| Project | `uv`, `ruff`, `pytest` |
| API | FastAPI + Pydantic, served by `uvicorn` |
| Database | PostgreSQL 17 + PostGIS, SQLAlchemy 2 Core (raw SQL with `text()`), hand-written Alembic migrations |
| Real time | `httpx2` + `gtfs-realtime-bindings`, two asyncio tasks in the background |
| Web | Jinja2 + htmx, MapLibre GL (served from `static/`, no CDN) with the [OpenFreeMap](https://openfreemap.org) Positron vector style |
| Infra | Docker: a multi-stage image built with uv that runs as a non-root user, and docker compose for the database and the app |

## Running it

You need [uv](https://docs.astral.sh/uv/) and Docker.

1. **Settings.** Copy `.env.example` to `.env` and fill in `GCBA_CLIENT_ID` and
   `GCBA_CLIENT_SECRET`. You can get yours at
   <https://api-transporte.buenosaires.gob.ar/registro>.
2. **Database.** `make up` starts Postgres + PostGIS and waits until it's
   ready. It also creates an empty `notibondi_test` database for the tests.
3. **Schema.** `make migrate`.
4. **GTFS data.** `make gtfs` downloads the static GTFS (~209 MB, about a
   minute) from the GCBA API to `data/gtfs.zip`, with the credentials from
   `.env`. Then run `make import` (about 3 minutes) and `make holidays`
   (loads `holidays.csv`).
5. **App.** `make dev` and open <http://localhost:8000>.

   Or run it in Docker instead: `docker compose up --build`, and open the same
   URL. The image runs a single uvicorn worker without `--reload`, so it's for
   running the app, not for developing it. Stop `make dev` first, because both
   use port 8000.

Other commands:

| Command | What it does |
| --- | --- |
| `make gtfs` | downloads the static GTFS again (the old zip is kept until the new one is complete) |
| `make check` | lint + tests (the database must be up) |
| `make fmt` | fixes lint and formats the code |
| `make pilot` | records the live feed of one line to `data/pilot.sqlite` |
| `docker compose run --rm app alembic upgrade head` | runs the migrations from the app image, without uv |

When the app runs in Docker:

| Command | What it does |
| --- | --- |
| `docker compose ps -a` | whether the app is running, or its exit code if it stopped |
| `docker compose logs -f app` | the app's logs, live (`--tail 50` for the last lines) |

The tests use the `notibondi_test` database and a small GTFS in
`tests/fixtures/gtfs-mini/`, so they don't need the real import or the GCBA
credentials.

## API

Every page uses the same query functions as the JSON API. The docs are at
`/docs` while the app runs.

| Endpoint | Returns |
| --- | --- |
| `GET /health` | `ok` or `degraded`, and the age of both live feeds (only the arrivals feed can make it `degraded`) |
| `GET /api/v1/stops/nearby?lat=&lon=&radius=` | stops around a point |
| `GET /api/v1/stops/search?q=` | stops by name |
| `GET /api/v1/stops/{stop_id}/arrivals` | next arrivals, each tagged live or scheduled |
| `GET /api/v1/routes/search?q=` | lines by number |
| `GET /api/v1/routes/{route_id}/geojson` | both directions and their stops, as a GeoJSON `FeatureCollection` |
| `GET /api/v1/routes/{route_id}/vehicles` | the line's live buses as GeoJSON points, with their direction and position time (older than 5 minutes are left out) |

## Design decisions

- **No Redis, and one process.** The live data lives in the memory of the
  process. With one instance that's enough, and it's one service less to run.
  The two decisions go together: uvicorn runs with a single worker, because
  each worker would start its own background tasks, hit the GCBA again and
  keep its own copy of the data.
- **Background tasks, not per-request calls.** Two asyncio tasks download the
  city feeds, no matter how many users there are: arrivals (`tripUpdates`)
  every 30 s at rush hour and every 60 s the rest of the day, and bus
  positions (the whole `vehiclePositions` feed) every 60 s. The data only
  changes once a minute, so asking more often adds traffic, not freshness.
  They are separate tasks so a stuck download of one feed never delays the
  other. Requests only read from memory.
- **Failures.** If a download fails, the app keeps serving the last good data,
  and `/health` reports how old it is. Retries start after 5 s and double
  (5, 10, 20…) up to the normal interval, and the first success goes back to
  the normal pace. Connecting has
  a 5 s timeout, so a GCBA that's down fails fast, while a slow but working
  download still gets 30-45 s.
- **Live and scheduled, mixed by line name.** The real-time `route_id` and
  `trip_id` don't match the static GTFS. Worse, they collide with IDs that
  exist there, so a direct join silently gives the wrong line. Stop IDs do
  match, so live and scheduled arrivals are merged per stop, by line name.
- **The midnight trap.** A trip belongs to the service day it started on, so
  after midnight the buses still running from yesterday have times like
  `24:30:00`. The arrivals query looks at both service days.
- **Holidays.** The GTFS calendar only has dates from the first half of 2021,
  so the service of each day (weekday, Saturday, Sunday or holiday) is worked
  out from the day of the week plus `holidays.csv`. The holiday service
  number is fixed in the code, and the import fails if the calendar doesn't
  agree with it.
- **One service per day.** Besides its 4 services, the GTFS has ~17,900
  "dashed" ones (`1-35`), each with a single trip. The import stores them as
  the service before the dash, so they show up with the rest of the day.
- **Precomputed tables.** The import builds `stop_routes` (the lines at each
  stop) and `route_stops` (the stops of each line and direction, using the
  trip with most stops). `route_stops` is 14 MB; the index it replaces would
  be about 1 GB.
- **Fast import.** `stop_times` and `shapes` load with `COPY`, and the big
  index is dropped before the load and built once at the end.

## Known limits

- **Live data covers about 32% of the lines** (340 of 1074 on 2026-11-17), so
  most arrivals are still scheduled times. The live routes are matched to
  static lines by their stops, and the static GTFS (2021) only knows 41% of
  the stops in today's feed.
- **Some routes on the map may be outdated.** They come from the 2021 GTFS,
  so a line that changed its streets since then is drawn where it used to go.
- **Buses without a trip are not shown.** About 29% of the positions feed has
  no `trip`, so there's no way to know their line.
- About 222 stop names have `?` instead of `ñ`. That's how they come in the
  source data.
