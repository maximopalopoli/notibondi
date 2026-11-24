import asyncio
import contextlib
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import httpx2
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Connection
from starlette.concurrency import run_in_threadpool

from notibondi.config import get_settings
from notibondi.db import Conn, DbEngine, get_engine
from notibondi.fixtures import load_fixtures
from notibondi.geocode import GeocodeBusy, GeocodeError, Geocoder
from notibondi.realtime import (
    line_number,
    load_directions_by_stop,
    load_lines_by_stop,
    load_overrides,
    load_route_names,
    merge_arrivals,
    save_route_names,
    unknown_overrides,
)
from notibondi.routes import (
    LINE_NAME,
    LINE_NAME_PATTERN,
    Route,
    get_route,
    line_groups,
    route_exists,
    route_geojson,
    route_headsigns,
    search_routes,
)
from notibondi.schedules import Arrival, next_arrivals, now
from notibondi.static_url import StaticUrl
from notibondi.stops import (
    MAX_FAVORITES,
    MAX_RADIUS_M,
    MAX_SEARCH_LIMIT,
    FavoriteStop,
    NearbyStop,
    Stop,
    favorite_lines,
    favorite_stops,
    find_farther_line_stops,
    find_nearby_stops,
    search_stops,
    stop_exists,
    stop_line_paths,
    stop_lines,
)
from notibondi.tiles import TILES_DIR, TILES_PREFIX, OptionalStaticFiles, TilesUrl
from notibondi.walk import leave_in, walk_minutes
from notibondi.worker import (
    Health,
    LiveFeed,
    feed_health,
    refresh_forever,
    refresh_route_names_forever,
    refresh_vehicles_forever,
    vehicles_geojson,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
# httpx2 logs every request URL at INFO, and the GCBA URL carries the secret
logging.getLogger("httpx2").setLevel(logging.WARNING)


class DropQueryString(logging.Filter):
    """Log the path of each request without its query string.

    The query carries where the user is (lat, lon) or the address they
    typed (q): one access log line per search would be a record of where
    each person goes. The path is enough to see traffic and errors."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn's args: client, method, path with query, HTTP version, status
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, version, status = record.args
            record.args = (client, method, str(path).partition("?")[0], version, status)
        return True


logging.getLogger("uvicorn.access").addFilter(DropQueryString())


def save_names(names: dict[str, str]) -> None:
    with get_engine().begin() as conn:
        save_route_names(conn, names)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    with get_engine().connect() as conn:
        lines_by_stop = load_lines_by_stop(conn)
        directions_by_stop = load_directions_by_stop(conn)
        route_names = load_route_names(conn)
    overrides = load_overrides()
    static_lines = {line for lines in lines_by_stop.values() for line in lines}
    if skipped := unknown_overrides(overrides, static_lines):
        logging.getLogger(__name__).warning(
            "route_overrides.csv: %d rows with a line the GTFS doesn't have: %s",
            len(skipped),
            ", ".join(sorted(skipped)),
        )
    app.state.live = LiveFeed(route_names=route_names, overrides=overrides)
    async with httpx2.AsyncClient(timeout=30) as client:
        settings = get_settings()
        tasks = []
        if settings.live_feeds == "gcba":
            # Separate tasks, so a slow download never delays the others
            tasks = [
                asyncio.create_task(
                    refresh_forever(
                        app.state.live,
                        client,
                        settings,
                        lines_by_stop,
                        directions_by_stop,
                    )
                ),
                asyncio.create_task(
                    refresh_vehicles_forever(app.state.live, client, settings)
                ),
                asyncio.create_task(
                    refresh_route_names_forever(
                        app.state.live, client, settings, save_names
                    )
                ),
            ]
        elif settings.live_feeds == "fixtures":
            load_fixtures(app.state.live, lines_by_stop, directions_by_stop)
        # Not tied to LIVE_FEEDS: that setting is about the GCBA
        app.state.geocoder = Geocoder(client, settings)
        yield
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(lifespan=lifespan)

BASE_DIR = Path(__file__).parent

Lat = Annotated[float, Query(ge=-90, le=90)]
Lon = Annotated[float, Query(ge=-180, le=180)]
Radius = Annotated[int, Query(gt=0, le=MAX_RADIUS_M)]
DistanceM = Annotated[int | None, Query(ge=0, le=MAX_RADIUS_M)]

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
# The Protomaps file, if data/tiles has one. Not under /static/: the service
# worker caches /static/, and the Cache API can't keep Range (206) answers.
# Without the folder the app starts the same (the maps then use OpenFreeMap)
# and /tiles/ is a 404
tiles_files = OptionalStaticFiles(TILES_DIR)
app.mount(TILES_PREFIX, tiles_files, name="tiles")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
# Every static file with ?v=<hash of its content>, so a deploy is never stale
templates.env.globals["static_url"] = StaticUrl(BASE_DIR / "static")
templates.env.globals["tiles_url"] = TilesUrl(TILES_DIR)
# The arrivals only take a distance up to this ("Salí en" is for walking)
templates.env.globals["MAX_RADIUS_M"] = MAX_RADIUS_M


def get_live(request: Request) -> LiveFeed:
    return request.app.state.live


Live = Annotated[LiveFeed, Depends(get_live)]


def get_geocoder(request: Request) -> Geocoder:
    return request.app.state.geocoder


GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]


def arrivals_for(
    conn: Connection,
    live: LiveFeed,
    stop_id: str,
    at: datetime,
    line: str | None = None,
) -> list[Arrival]:
    """Live arrivals mixed with the schedule, or only the schedule if the
    feed is degraded (no good download yet, or older than 5 minutes). Of
    every line, or only of `line`."""
    scheduled = next_arrivals(conn, stop_id, at, line)
    if feed_health(live).status == "degraded":
        return scheduled
    # With a line (152A), also the buses of its number of unknown branch
    # ("152"): one of them may be a 152A
    live_arrivals = [
        a
        for a in live.index.get(stop_id, [])
        if line is None
        or a.line == line
        or (not a.branch_known and a.line == line_number(line))
    ]
    return merge_arrivals(live_arrivals, scheduled, at)


def query_string(**params) -> str:
    """ "?a=1&b=2" from the params that aren't None, or "" if none is."""
    kept = {k: v for k, v in params.items() if v is not None}
    return "?" + urlencode(kept) if kept else ""


templates.env.globals["query_string"] = query_string


@app.get("/health", response_model=Health)
def health(live: Live) -> Health:
    return feed_health(live)


@app.get("/api/v1/stops/nearby", response_model=list[NearbyStop])
def nearby_stops(
    lat: Lat,
    lon: Lon,
    conn: Conn,
    radius: Radius = 400,
):
    return find_nearby_stops(conn, lat, lon, radius)


# The browser checks /sw.js for a new version: no-cache, so it always asks
# (it can still get a 304), and no ?v=, because its URL must never change
NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    """At the root, not under /static/: a service worker only controls the
    URLs under its own folder."""
    return FileResponse(
        BASE_DIR / "static" / "sw.js", media_type="text/javascript", headers=NO_CACHE
    )


@app.get("/offline", response_class=HTMLResponse, include_in_schema=False)
def offline(request: Request):
    """Saved by the service worker on install, shown when a page can't load."""
    return templates.TemplateResponse(request, "offline.html", headers=NO_CACHE)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/stops", response_class=HTMLResponse, include_in_schema=False)
def stops_page(request: Request):
    return templates.TemplateResponse(request, "stops.html")


def stop_or_404(conn: Connection, stop_id: str) -> FavoriteStop:
    """A stop with its lines and position, as a favorite has them."""
    found = favorite_stops(conn, [stop_id])
    if not found:
        raise HTTPException(status_code=404, detail="Stop not found")
    return found[0]


# An optional line name in a query string: only letters and digits
MaybeLine = Annotated[str | None, Query(pattern=LINE_NAME_PATTERN)]


@app.get("/stops/{stop_id}", response_class=HTMLResponse, include_in_schema=False)
def stop_page(request: Request, conn: Conn, stop_id: str, line: MaybeLine = None):
    """A stop's own address: the stops page with the stop's panel open, as
    it looks after tapping "Ver parada" there (ui.js). With ?line, only that
    line's arrivals, as after tapping the stop on the line's map."""
    return templates.TemplateResponse(
        request,
        "stops.html",
        {"detail_stop": stop_or_404(conn, stop_id), "distance_m": None, "line": line},
    )


@app.get(
    "/partials/stops/{stop_id}/detail",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def stop_detail_partial(
    request: Request,
    conn: Conn,
    stop_id: str,
    distance_m: DistanceM = None,
    line: MaybeLine = None,
):
    """The panel of a stop, over the page you were on (ui.js opens it).
    With ?line (a stop tapped on a line's map), only that line's arrivals."""
    return templates.TemplateResponse(
        request,
        "partials/stop_detail.html",
        {
            "detail_stop": stop_or_404(conn, stop_id),
            "distance_m": distance_m,
            "line": line,
        },
    )


def stops_around(
    conn, lat: float, lon: float, radius: int
) -> tuple[list[NearbyStop], int | None]:
    """The stops within radius, then the nearest stop of each line that has
    none within radius, and where those farther ones start (None: none)."""
    near = find_nearby_stops(conn, lat, lon, radius)
    farther = find_farther_line_stops(conn, lat, lon, radius)
    return near + farther, (len(near) if farther else None)


@app.get("/partials/stops/nearby", response_class=HTMLResponse, include_in_schema=False)
def nearby_stops_partial(
    request: Request, lat: Lat, lon: Lon, conn: Conn, radius: Radius = 400
):
    stops, first_farther = stops_around(conn, lat, lon, radius)
    return templates.TemplateResponse(
        request,
        "partials/stops.html",
        {
            "stops": stops,
            "first_farther": first_farther,
            "origin": (lat, lon),
            "lines_show_buses": True,
            "empty_message": "No hay paradas cerca.",
        },
    )


OptLat = Annotated[float | None, Query(ge=-90, le=90)]
OptLon = Annotated[float | None, Query(ge=-180, le=180)]
# The home page shows the nearest one; /favorites, with ?all=true, all of them
ShowAll = Annotated[bool, Query(alias="all")]
# A favorite line as the browser keeps it: the line and its direction_id
FAVORITE_LINE = re.compile(r"[0-9A-Za-z]{1,10}:[01]")


@app.get(
    "/partials/stops/favorite", response_class=HTMLResponse, include_in_schema=False
)
def favorite_stop_partial(
    request: Request,
    conn: Conn,
    ids: Annotated[list[str], Query()],
    lat: OptLat = None,
    lon: OptLon = None,
    show_all: ShowAll = False,
):
    """The favorite stops. On the home page, the nearest one, or the user's
    first one when the browser doesn't say where the user is. With ?all
    (/favorites), all of them in the user's order, to move them around."""
    if len(ids) > MAX_FAVORITES or any(len(i) > 50 for i in ids):
        raise HTTPException(status_code=422, detail="Too many or too long ids")
    stops = favorite_stops(conn, ids, lat, lon, by_distance=not show_all)
    note = None
    if not show_all:
        stops = stops[:1]
        if stops and stops[0].distance_m is None:
            note = "Tu primera favorita: no sabemos dónde estás."
    return templates.TemplateResponse(
        request,
        "partials/stops.html",
        {
            "stops": stops,
            "note": note,
            "reorder": show_all,
            "empty_message": "Tus paradas favoritas ya no existen.",
        },
    )


@app.get(
    "/partials/lines/favorite", response_class=HTMLResponse, include_in_schema=False
)
def favorite_lines_partial(
    request: Request,
    conn: Conn,
    lines: Annotated[list[str], Query()],
    lat: OptLat = None,
    lon: OptLon = None,
    show_all: ShowAll = False,
):
    """The favorite lines ("108A:1"), each with its stop nearest to the
    user. Ordered like favorite_stop_partial."""
    if len(lines) > MAX_FAVORITES or not all(FAVORITE_LINE.fullmatch(f) for f in lines):
        raise HTTPException(status_code=422, detail="Too many or malformed lines")
    pairs = [
        (line, int(direction)) for line, direction in (f.split(":") for f in lines)
    ]
    favorites = favorite_lines(conn, pairs, lat, lon, by_distance=not show_all)
    if not show_all:
        favorites = favorites[:1]
    note = None
    if favorites and lat is None:
        note = "No sabemos dónde estás, así que no podemos buscar la parada más cerca."
    return templates.TemplateResponse(
        request,
        "partials/favorite_lines.html",
        {
            "favorites": favorites,
            "note": note,
            "reorder": show_all,
            "empty_message": "Tus líneas favoritas ya no existen.",
        },
    )


@app.get("/favorites", response_class=HTMLResponse, include_in_schema=False)
def favorites_page(request: Request):
    return templates.TemplateResponse(request, "favorites.html")


Q = Annotated[str, Query(min_length=2, max_length=100)]
Limit = Annotated[int, Query(gt=0, le=MAX_SEARCH_LIMIT)]


@app.get("/api/v1/stops/search", response_model=list[Stop])
def search_stops_api(q: Q, conn: Conn, limit: Limit = 20):
    return search_stops(conn, q, limit)


@app.get("/partials/stops/search", response_class=HTMLResponse, include_in_schema=False)
def search_stops_partial(
    request: Request, conn: Conn, q: Annotated[str, Query(max_length=100)] = ""
):
    q = q.strip()
    if len(q) < 2:
        return HTMLResponse("")
    stops = search_stops(conn, q, 20)
    return templates.TemplateResponse(
        request,
        "partials/stops.html",
        {"stops": stops, "empty_message": "No se encontraron paradas con ese nombre."},
    )


def message(text: str) -> HTMLResponse:
    # 200, not 4xx/5xx: htmx only swaps 2xx, and these are answers, not crashes
    return HTMLResponse(f'<p class="error" role="alert">{text}</p>')


@app.get(
    "/partials/stops/address", response_class=HTMLResponse, include_in_schema=False
)
async def address_stops_partial(
    request: Request,
    engine: DbEngine,
    geocoder: GeocoderDep,
    q: Annotated[str, Query(max_length=200)] = "",
):
    """The stops near an address, as if it were the user's location.

    It takes the engine, not a Conn: the search can wait seconds in line for
    Nominatim, and a connection held all that time by each waiting request
    would run the pool dry for every other page."""
    q = q.strip()
    if len(q) < 3:
        return message("Escribí una dirección, por ejemplo Triunvirato 3424.")
    try:
        place = await geocoder.search(q)
    except GeocodeBusy:
        # Expected under a flood: one line, not a traceback per request
        logging.getLogger(__name__).warning("geocode busy, search refused")
        return message("No pudimos buscar la dirección. Probá de nuevo en un rato.")
    except GeocodeError:
        logging.getLogger(__name__).warning("geocode failed", exc_info=True)
        return message("No pudimos buscar la dirección. Probá de nuevo en un rato.")
    if place is None:
        return message(
            "No encontramos esa dirección. Probá con calle y altura, "
            "por ejemplo Triunvirato 3424."
        )

    def stops_near_place():
        with engine.connect() as conn:
            return stops_around(conn, place.lat, place.lon, 400)

    # A sync query from an async route: in a thread, so it doesn't block the loop
    stops, first_farther = await run_in_threadpool(stops_near_place)
    return templates.TemplateResponse(
        request,
        "partials/stops.html",
        {
            "stops": stops,
            "first_farther": first_farther,
            "place": place.label,
            "origin": (place.lat, place.lon),
            "lines_show_buses": True,
            "empty_message": "No hay paradas cerca de esa dirección.",
        },
    )


def current_time() -> datetime:
    return now()


Now = Annotated[datetime, Depends(current_time)]


@app.get("/api/v1/stops/{stop_id}/arrivals", response_model=list[Arrival])
def stop_arrivals(stop_id: str, conn: Conn, live: Live, at: Now):
    if not stop_exists(conn, stop_id):
        raise HTTPException(status_code=404, detail="Stop not found")
    return arrivals_for(conn, live, stop_id, at)


@app.get(
    "/partials/stops/{stop_id}/arrivals",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def stop_arrivals_partial(
    request: Request,
    stop_id: str,
    conn: Conn,
    live: Live,
    at: Now,
    distance_m: DistanceM = None,
    line: MaybeLine = None,
):
    """The arrivals of a stop; with ?line, only that line's (a favorite line
    on the home page)."""
    if not stop_exists(conn, stop_id):
        raise HTTPException(status_code=404, detail="Stop not found")
    arrivals = arrivals_for(conn, live, stop_id, at, line)
    # Without a distance (search by name) there's nothing to walk from
    walk = walk_minutes(distance_m) if distance_m is not None else None
    rows = [
        (a, leave_in(a.minutes, walk) if walk is not None else None) for a in arrivals
    ]
    return templates.TemplateResponse(
        request,
        "partials/arrivals.html",
        {"stop_id": stop_id, "distance_m": distance_m, "line": line, "rows": rows},
    )


@app.get("/api/v1/stops/{stop_id}/vehicles")
def stop_vehicles_api(
    stop_id: str,
    conn: Conn,
    live: Live,
    line: Annotated[str | None, Query(max_length=10)] = None,
):
    """The live buses of one line that stops here (the one tapped on the
    stops page), or of every line without ?line. With ?line, only the ones
    going the way this stop is: coming to it, or already past it."""
    lines = stop_lines(conn, stop_id)
    if lines is None:
        raise HTTPException(status_code=404, detail="Stop not found")
    if line is not None:
        if line not in lines:
            raise HTTPException(status_code=404, detail="Line doesn't stop here")
        lines = [line]
    # Each live route_id goes one way: the ones with arrivals here go this
    # stop's way. If the feed predicts nothing here, all of them, not a guess.
    route_ids = (live.routes_by_stop.get(stop_id) or None) if line else None
    at = time.time()
    # A bus of an unknown branch comes once per branch of its number
    features = {}
    for name in lines:
        for feature in vehicles_geojson(live, name, at, route_ids)["features"]:
            features.setdefault(feature["id"], feature)
    return JSONResponse(
        content={"type": "FeatureCollection", "features": list(features.values())},
        media_type="application/geo+json",
    )


LineQ = Annotated[str, Query(pattern=LINE_NAME_PATTERN)]


@app.get("/api/v1/routes/search", response_model=list[Route])
def routes_by_query(q: LineQ, conn: Conn):
    return search_routes(conn, q)


@app.get("/api/v1/stops/{stop_id}/lines/{line}/geojson")
def stop_line_paths_api(stop_id: str, line: str, conn: Conn):
    """The path of a line that stops here, the way it comes to this stop."""
    lines = stop_lines(conn, stop_id)
    if lines is None:
        raise HTTPException(status_code=404, detail="Stop not found")
    if line not in lines:
        raise HTTPException(status_code=404, detail="Line doesn't stop here")
    return JSONResponse(
        content=stop_line_paths(conn, stop_id, line),
        media_type="application/geo+json",
    )


@app.get("/api/v1/routes/{route_id}/geojson")
def route_geojson_api(route_id: str, conn: Conn):
    if not route_exists(conn, route_id):
        raise HTTPException(status_code=404, detail="Route not found")
    return JSONResponse(
        content=route_geojson(conn, route_id), media_type="application/geo+json"
    )


@app.get("/api/v1/routes/{route_id}/vehicles")
def route_vehicles_api(route_id: str, conn: Conn, live: Live):
    route = get_route(conn, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return JSONResponse(
        content=vehicles_geojson(live, route.route_short_name, time.time()),
        media_type="application/geo+json",
    )


@app.get("/routes", response_class=HTMLResponse, include_in_schema=False)
def routes_page(request: Request, conn: Conn):
    return templates.TemplateResponse(
        request, "routes.html", {"groups": line_groups(conn)}
    )


@app.get(
    "/partials/routes/search", response_class=HTMLResponse, include_in_schema=False
)
def search_routes_partial(
    request: Request, conn: Conn, q: Annotated[str, Query(max_length=100)] = ""
):
    q = q.strip()
    if not LINE_NAME.fullmatch(q):
        return HTMLResponse("")
    routes = search_routes(conn, q)
    headsigns = route_headsigns(conn, [r.route_id for r in routes])
    return templates.TemplateResponse(
        request, "partials/routes.html", {"routes": routes, "headsigns": headsigns}
    )


@app.get("/routes/{route_id}", response_class=HTMLResponse, include_in_schema=False)
def route_page(route_id: str, request: Request, conn: Conn):
    route = get_route(conn, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return templates.TemplateResponse(request, "route.html", {"route": route})
