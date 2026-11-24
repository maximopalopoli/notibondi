# notibondi

Notibondi is a web app for Buenos Aires buses, useful to find nearby stops,
see when the next buses arrive (live when the city feed has data, scheduled
when it doesn't), and see a line's route and its live buses on a map.

## Features

- **Nearby stops**: the stops around your location, or around an address
  ("Triunvirato 3424") when the browser can't find you, with the lines that
  stop there.
- **Stop search**: by name ("plaza italia").
- **Arrivals**: the next buses at a stop. Live times from the GCBA real-time
  feed, and the GTFS schedule for lines that have no live data. From a nearby
  stop, each arrival also says when to leave ("Salí en 4 min", "No llegás").
- **Lines and routes**: search a line by number ("152" gives 152A, 152B…) and
  see both directions on a map, each on its own side of the street, with
  arrows that show where each one goes and a legend to show one direction or
  both. Tapping a stop on the map opens its arrivals for that line.
- **Live buses**: the line's buses on the same map, colored by direction and
  refreshed every 30 s. A line with no live data says so under the map.
- **Favorites**: save stops and lines, and the home page shows them first.
- **Installable**: it's a PWA, so it can be added to a phone's home screen,
  with its own icon and an offline page.

## Stack

| Layer | Tools |
| --- | --- |
| Project | `uv`, `ruff`, `pytest` |
| API | FastAPI + Pydantic, served by `uvicorn` |
| Database | PostgreSQL 17 + PostGIS, SQLAlchemy 2 Core (raw SQL with `text()`), hand-written Alembic migrations |
| Real time | `httpx2` + `gtfs-realtime-bindings`, two asyncio tasks in the background |
| Addresses | [Nominatim](https://nominatim.org) (OpenStreetMap), called from the server |
| Web | Jinja2 + htmx, MapLibre GL (served from `static/`, no CDN), a service worker and a web manifest |
| Map | Our own [Protomaps](https://protomaps.com) file of the AMBA, with its fonts and icons, served by the app; [OpenFreeMap](https://openfreemap.org) Positron when that file is missing |
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
5. **Map tiles (optional).** Without them the maps use OpenFreeMap, so you
   can skip this step. To serve your own map, install the
   [`pmtiles` CLI](https://github.com/protomaps/go-pmtiles/releases), pick a
   date from <https://maps.protomaps.com/builds> and run
   `make tiles BUILD=20261118 NAME=amba-2026-11`. It cuts the AMBA (~75 MB)
   out of the daily world build into `data/tiles/`. The app uses the newest
   `.pmtiles` file in that folder.
6. **App.** `make dev` and open <http://localhost:8000>.

   With `--reload`, every saved `.py` restarts the app and downloads the live
   feeds again (`tripUpdates` alone is ~9 MB and can take 30 s). To work
   without the GCBA, set `LIVE_FEEDS` in `.env`:

   | `LIVE_FEEDS` | What the app does |
   | --- | --- |
   | `gcba` (default) | downloads the live feeds in the background, as in production |
   | `fixtures` | loads the recorded 108 feeds from `tests/fixtures/` once, moved to the current time, so the 108A has buses and live arrivals with no network |
   | `off` | no live data at all: only scheduled times |

   `fixtures` only works from the repo, because the Docker image doesn't
   have `tests/`. In both `fixtures` and `off`, `/health` doesn't mean the
   GCBA is up.

   Or run it in Docker instead: `docker compose up --build`, and open the same
   URL. The image runs a single uvicorn worker without `--reload`, so it's for
   running the app, not for developing it. Stop `make dev` first, because both
   use port 8000.

Other commands:

| Command | What it does |
| --- | --- |
| `make gtfs` | downloads the static GTFS again (the old zip is kept until the new one is complete) |
| `make tiles BUILD=… NAME=…` | cuts a new map of the AMBA from a Protomaps build |
| `make check` | lint + tests (the database must be up) |
| `make fmt` | fixes lint and formats the code |
| `make pilot` | records the live feed of one line to `data/pilot.sqlite` |
| `make track` | records every AMBA bus position, once a minute, to `data/track.sqlite` (~1 GB a day) |
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
- **Background tasks, not per-request calls.** Asyncio tasks download the
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
  exist there, so a direct join silently gives the wrong line. So each live
  `route_id` gets its line name first from `vehiclePositionsSimple`, a JSON
  feed that names it (`152`, and the stops pick the branch; messy names like
  `85 A - P. Alsina` or `247-5` are read as `85A` and `247R5`), and otherwise
  from the stops it shares with the static lines, since stop IDs do match.
  Live and scheduled arrivals are then merged per stop, by line name. The
  names are downloaded every 10 minutes and saved in `route_names`, because
  that feed is slow and only lists the routes with a bus right now. After a
  restart the app starts with the saved ones, instead of waiting for buses.
- **Buses of an unknown branch show on every branch.** Many live names say
  the line and not the branch (`152`, `133 Pte. Saavedra`), and sometimes
  the stops can't pick one. Those buses show up faded on the map of every
  branch of their line, with a note, and at the stops of their number as
  "ramal sin confirmar": a 152A user may see a 152C bus, but without them
  the 152 had no buses at all.
- **Hand-checked lines win.** `src/notibondi/route_overrides.csv` gives the
  line of live `route_id`s that the automatic match gets wrong or can't
  resolve. Each row says how it was checked (mostly by matching recorded
  bus positions with the routes) and when. It's loaded at startup, and its
  rows win over the automatic match.
- **Our own map.** The basemap is one Protomaps file of the AMBA, served by
  the app, and the browser reads it in pieces with HTTP range requests. No
  tile server, no API key and no usage limits from a third party. If the
  file is missing, the maps fall back to OpenFreeMap.
- **Static files with a hash in the URL.** Each file in `static/` is linked
  with a hash of its content, so a browser (or the service worker) never
  keeps an old copy after a deploy.
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

## Real-time coverage

The city's live feeds and the static GTFS (2021) don't share IDs, so every
live `route_id` has to be matched to a line before its buses can show (see
"Live and scheduled, mixed by line name" above). This section says how much
of the feed the app can use, and why the rest is missing.

### How much

Measured on 2026-11-24 (Tuesday, 9:40) on the live feed, with different
versions of `route_overrides.csv`:

| Overrides | Line numbers with live arrivals | Branches with live arrivals | Stops with live arrivals |
| --- | --- | --- | --- |
| None | 213 of 275 (77%) | 580 of 1,072 (54%) | 27,378 |
| 104 rows (one hour of traces, 2026-11-18) | 226 of 275 (82%) | 614 of 1,072 (57%) | 29,521 |
| 274 rows (three days of traces, 2026-11-20) | 247 of 275 (90%) | 685 of 1,072 (64%) | 33,813 |

The numbers count arrivals of an unknown branch ("ramal sin confirmar"), the
branches don't. They move during the day, because the names feed only lists
the routes that have a bus right now.

### Why some buses are missing

- **Buses without a trip.** About 29% of the positions feed has no `trip`,
  so there's no way to know the line. Most of those buses are moving. In
  three feeds over 38 minutes (2026-11-16), many got a `trip` again a few
  minutes later (they were between two trips), but almost half went the
  whole time without one.
- **Names the GTFS doesn't have.** Some live names are branches the 2021
  GTFS doesn't know (`1 B`, `504METALURG`), and a few lines aren't in it at
  all (239, 507).
- **Names that don't say the branch.** `152` or `133 Pte. Saavedra` give the
  number only, and some branches share so many stops that the stops can't
  pick one. The headsign letter doesn't help either: `Ramal A` often isn't
  branch A in the GTFS.
- **Routes with no name.** Some `route_id`s never appear in the names feed,
  and their stops are unknown too. For example, the 114 runs as `route_id`
  236 without ever being named.
- **New stops.** The 2021 GTFS only knows 41% of the stops in today's
  arrivals feed. An arrival at a stop the app doesn't know can't be shown.
- **Wrong names.** The names feed is sometimes wrong: `route_id`s 1385 and
  1386 are named `8D` but their buses run the 5B.

### What the app does about it

- **Buses of an unknown branch still show**, faded on the map of every
  branch of their number and as "ramal sin confirmar" at its stops.
- **`route_overrides.csv`** fixes `route_id`s by hand. The rows come from
  bus positions recorded over several days (`make track`) and matched with
  the routes. A `route_id` keeps its line number from day to day (1,112 of
  1,115 did, over three weekdays), and almost always its branch too, so a
  row checked once stays valid.

### What could raise it

- More override rows. 13 rows from the three days of traces are left out
  until someone checks them on a map, and more days of positions will give
  more rows.
- Rebuilding the routes that changed since 2021 from recorded positions,
  once there are a few weeks of them.
- Remembering the line of each bus (`vehicle.id`) from the feeds where it
  did have a `trip`, for buses between two trips.
- A newer GTFS, if the city publishes one.

## Known limits

- **Addresses are searched in CABA first.** Street names repeat across the
  AMBA ("Corrientes 1500" is also in Quilmes and Olivos), so an address in
  the province needs its locality: "Mitre 500, Quilmes". Nominatim allows one
  request per second, so a busy instance would need its own Nominatim server.

- **Not every bus has live data.** About 9 in 10 line numbers and 2 in 3
  branches do. See [Real-time coverage](#real-time-coverage) for the numbers
  and the reasons.
- **Some routes on the map may be outdated.** They come from the 2021 GTFS,
  so a line that changed its streets since then is drawn where it used to go.
- **The same bus can show twice at a stop.** A live bus of an unknown
  branch shows as its number ("152 · ramal sin confirmar"), and the
  scheduled arrivals of each branch (152A, 152B…) still show next to it,
  because the app can't tell which branch that bus is. So "152 in 3 min"
  and "152A in 4 min" may be the same bus.
- About 222 stop names have `?` instead of `ñ`. That's how they come in the
  source data.

## Data and credits

- Bus data: static GTFS and real-time feeds from the
  [API de Transporte](https://api-transporte.buenosaires.gob.ar) of the
  Gobierno de la Ciudad de Buenos Aires.
- Map data: © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors, through [Protomaps](https://protomaps.com) (and
  [OpenFreeMap](https://openfreemap.org) as the fallback).
- Address search: [Nominatim](https://nominatim.org), with OpenStreetMap data.

## License

The code is under the [MIT License](LICENSE). The data and the map have their
own licenses and credits (see above).
