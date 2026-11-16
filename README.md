# notibondi

Notibondi is a web app for Buenos Aires buses, useful to find nearby stops,
see when the next buses arrive (live when the city feed has data, scheduled
when it doesn't), and see a line's route on a map.

## Features

- **Nearby stops**: the stops around a point, with the lines that stop there.
- **Stop search**: by name ("plaza italia").
- **Arrivals**: the next buses at a stop. Live times from the GCBA real-time
  feed, and the GTFS schedule for lines that have no live data.
- **Lines and routes**: search a line by number ("152" gives 152A, 152B…) and
  see both directions on a map.

## Stack

| Layer | Tools |
| --- | --- |
| Project | `uv`, `ruff`, `pytest` |
| API | FastAPI + Pydantic, served by `uvicorn` |
| Database | PostgreSQL 17 + PostGIS, SQLAlchemy 2 Core (raw SQL with `text()`), hand-written Alembic migrations |
| Real time | `httpx2` + `gtfs-realtime-bindings`, an asyncio task in the background |
| Web | Jinja2 + htmx, MapLibre GL (served from `static/`, no CDN) with OSM tiles |
| Infra | docker compose (only the database, for now) |

## Running it

You need [uv](https://docs.astral.sh/uv/) and Docker.

1. **Settings.** Copy `.env.example` to `.env` and fill in `GCBA_CLIENT_ID` and
   `GCBA_CLIENT_SECRET`. You can get yours at
   <https://api-transporte.buenosaires.gob.ar/registro>.
2. **Database.** `make up` starts Postgres + PostGIS and waits until it's
   ready. It also creates an empty `notibondi_test` database for the tests.
3. **Schema.** `make migrate`.
4. **GTFS data.** Download the static GTFS (~209 MB) to `data/gtfs.zip`:

   ```sh
   curl -o data/gtfs.zip https://cdn.buenosaires.gob.ar/datosabiertos/datasets/transporte-y-obras-publicas/colectivos-gtfs/colectivos-gtfs.zip
   ```

   Then run `make import` (about 3 minutes, ~29M `stop_times`) and
   `make holidays` (loads `holidays.csv`).
5. **App.** `make dev` and open <http://localhost:8000>.

Other commands:

| Command | What it does |
| --- | --- |
| `make check` | lint + tests (the database must be up) |
| `make fmt` | fixes lint and formats the code |
| `make pilot` | records the live feed of one line to `data/pilot.sqlite` |

The tests use the `notibondi_test` database and a small GTFS in
`tests/fixtures/gtfs-mini/`, so they don't need the real import or the GCBA
credentials.

## API

Every page uses the same query functions as the JSON API. The docs are at
`/docs` while the app runs.

| Endpoint | Returns |
| --- | --- |
| `GET /health` | `ok` or `degraded`, and the age of the live feed |
| `GET /api/v1/stops/nearby?lat=&lon=&radius=` | stops around a point |
| `GET /api/v1/stops/search?q=` | stops by name |
| `GET /api/v1/stops/{stop_id}/arrivals` | next arrivals, each tagged live or scheduled |
| `GET /api/v1/routes/search?q=` | lines by number |
| `GET /api/v1/routes/{route_id}/geojson` | both directions and their stops, as a GeoJSON `FeatureCollection` |

## Design decisions

- **No Redis.** The live feed lives in the memory of the process. With one
  instance that's enough, and it's one service less to run.
- **One background worker.** The city feed is downloaded every 30 s at rush
  hour and every 60 s the rest of the day, no matter how many users there are.
  The data only changes once a minute, so asking more often adds traffic, not
  freshness. If a download fails, the app keeps serving the last good feed,
  and `/health` reports how old it is.
- **Live and scheduled, mixed by line name.** The real-time `route_id` and
  `trip_id` don't match the static GTFS. Worse, they collide with IDs that
  exist there, so a direct join silently gives the wrong line. Stop IDs do
  match, so live and scheduled arrivals are merged per stop, by line name.
- **The midnight trap.** A trip belongs to the service day it started on, so
  after midnight the buses still running from yesterday have times like
  `24:30:00`. The arrivals query looks at both service days.
- **Holidays.** The GTFS calendar only has dates from 2019, so the service of
  each day (weekday, Saturday, Sunday or holiday) is worked out from the day
  of the week plus `holidays.csv`.
- **Precomputed tables.** The import builds `stop_routes` (the lines at each
  stop) and `route_stops` (the stops of each line and direction, using the
  trip with most stops). `route_stops` is 14 MB; the index it replaces would
  be about 1 GB.
- **Fast import.** `stop_times` and `shapes` load with `COPY`, and the big
  index is dropped before the load and built once at the end.

## Known limits

- Only a small share of the live routes can be matched to static lines, so
  most arrivals are scheduled times.
- About 228 stop names have `?` instead of `ñ`. That's how they come in the
  source data.
