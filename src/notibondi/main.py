import asyncio
import contextlib
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import httpx2
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Connection
from starlette.concurrency import run_in_threadpool

from notibondi.config import get_settings
from notibondi.db import Conn, get_engine
from notibondi.fixtures import load_fixtures
from notibondi.geocode import GeocodeError, Geocoder
from notibondi.realtime import (
    load_lines_by_stop,
    load_route_names,
    merge_arrivals,
    save_route_names,
)
from notibondi.routes import (
    Route,
    get_route,
    route_exists,
    route_geojson,
    search_routes,
)
from notibondi.schedules import Arrival, next_arrivals, now
from notibondi.stops import (
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


def save_names(names: dict[str, str]) -> None:
    with get_engine().begin() as conn:
        save_route_names(conn, names)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    with get_engine().connect() as conn:
        lines_by_stop = load_lines_by_stop(conn)
        route_names = load_route_names(conn)
    app.state.live = LiveFeed(route_names=route_names)
    async with httpx2.AsyncClient(timeout=30) as client:
        settings = get_settings()
        tasks = []
        if settings.live_feeds == "gcba":
            # Separate tasks, so a slow download never delays the others
            tasks = [
                asyncio.create_task(
                    refresh_forever(app.state.live, client, settings, lines_by_stop)
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
            load_fixtures(app.state.live, lines_by_stop)
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
templates = Jinja2Templates(directory=BASE_DIR / "templates")


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
    live_arrivals = [
        a for a in live.index.get(stop_id, []) if line is None or a.line == line
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


@app.get("/stops/{stop_id}", response_class=HTMLResponse, include_in_schema=False)
def stop_page(request: Request, conn: Conn, stop_id: str):
    """A stop's own address: the stops page with the stop's panel open, as
    it looks after tapping "Ver parada" there (ui.js)."""
    return templates.TemplateResponse(
        request,
        "stops.html",
        {"detail_stop": stop_or_404(conn, stop_id), "distance_m": None},
    )


@app.get(
    "/partials/stops/{stop_id}/detail",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def stop_detail_partial(
    request: Request, conn: Conn, stop_id: str, distance_m: DistanceM = None
):
    """The panel of a stop, over the page you were on (ui.js opens it)."""
    return templates.TemplateResponse(
        request,
        "partials/stop_detail.html",
        {"detail_stop": stop_or_404(conn, stop_id), "distance_m": distance_m},
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
    conn: Conn,
    geocoder: GeocoderDep,
    q: Annotated[str, Query(max_length=200)] = "",
):
    """The stops near an address, as if it were the user's location."""
    q = q.strip()
    if len(q) < 3:
        return message("Escribí una dirección, por ejemplo Triunvirato 3424.")
    try:
        place = await geocoder.search(q)
    except GeocodeError:
        logging.getLogger(__name__).warning("geocode failed", exc_info=True)
        return message("No pudimos buscar la dirección. Probá de nuevo en un rato.")
    if place is None:
        return message(
            "No encontramos esa dirección. Probá con calle y altura, "
            "por ejemplo Triunvirato 3424."
        )
    # A sync query from an async route: in a thread, so it doesn't block the loop
    stops, first_farther = await run_in_threadpool(
        stops_around, conn, place.lat, place.lon, 400
    )
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
):
    if not stop_exists(conn, stop_id):
        raise HTTPException(status_code=404, detail="Stop not found")
    arrivals = arrivals_for(conn, live, stop_id, at)
    # Without a distance (search by name) there's nothing to walk from
    walk = walk_minutes(distance_m) if distance_m is not None else None
    rows = [
        (a, leave_in(a.minutes, walk) if walk is not None else None) for a in arrivals
    ]
    return templates.TemplateResponse(
        request,
        "partials/arrivals.html",
        {"stop_id": stop_id, "distance_m": distance_m, "rows": rows},
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
    for line in lines:
        for feature in vehicles_geojson(live, line, at)["features"]:
            features.setdefault(feature["id"], feature)
    return JSONResponse(
        content={"type": "FeatureCollection", "features": list(features.values())},
        media_type="application/geo+json",
    )


# search_routes puts the line name inside a regex, so only letters and digits
LINE_NAME_PATTERN = "^[0-9A-Za-z]{1,10}$"
LINE_NAME = re.compile(LINE_NAME_PATTERN)
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
def routes_page(request: Request):
    return templates.TemplateResponse(request, "routes.html")


@app.get(
    "/partials/routes/search", response_class=HTMLResponse, include_in_schema=False
)
def search_routes_partial(
    request: Request, conn: Conn, q: Annotated[str, Query(max_length=100)] = ""
):
    q = q.strip()
    if not LINE_NAME.fullmatch(q):
        return HTMLResponse("")
    return templates.TemplateResponse(
        request, "partials/routes.html", {"routes": search_routes(conn, q)}
    )


@app.get("/routes/{route_id}", response_class=HTMLResponse, include_in_schema=False)
def route_page(route_id: str, request: Request, conn: Conn):
    route = get_route(conn, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return templates.TemplateResponse(request, "route.html", {"route": route})
