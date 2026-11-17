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

from notibondi.config import get_settings
from notibondi.db import Conn, get_engine
from notibondi.realtime import load_lines_by_stop, merge_arrivals
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
    NearbyStop,
    Stop,
    find_nearby_stops,
    search_stops,
    stop_exists,
)
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


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    with get_engine().connect() as conn:
        lines_by_stop = load_lines_by_stop(conn)
    app.state.live = LiveFeed()
    async with httpx2.AsyncClient(timeout=30) as client:
        settings = get_settings()
        # Separate tasks, so a slow download never delays the others
        tasks = [
            asyncio.create_task(
                refresh_forever(app.state.live, client, settings, lines_by_stop)
            ),
            asyncio.create_task(
                refresh_vehicles_forever(app.state.live, client, settings)
            ),
            asyncio.create_task(
                refresh_route_names_forever(app.state.live, client, settings)
            ),
        ]
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

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def get_live(request: Request) -> LiveFeed:
    return request.app.state.live


Live = Annotated[LiveFeed, Depends(get_live)]


def arrivals_for(
    conn: Connection, live: LiveFeed, stop_id: str, at: datetime
) -> list[Arrival]:
    """Live arrivals mixed with the schedule, or only the schedule if the
    feed is degraded (no good download yet, or older than 5 minutes)."""
    scheduled = next_arrivals(conn, stop_id, at)
    if feed_health(live).status == "degraded":
        return scheduled
    return merge_arrivals(live.index.get(stop_id, []), scheduled, at)


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


@app.get("/partials/stops/nearby", response_class=HTMLResponse, include_in_schema=False)
def nearby_stops_partial(
    request: Request, lat: Lat, lon: Lon, conn: Conn, radius: Radius = 400
):
    stops = find_nearby_stops(conn, lat, lon, radius)
    return templates.TemplateResponse(
        request,
        "partials/stops.html",
        {"stops": stops, "empty_message": "No hay paradas cerca."},
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
    request: Request, stop_id: str, conn: Conn, live: Live, at: Now
):
    if not stop_exists(conn, stop_id):
        raise HTTPException(status_code=404, detail="Stop not found")
    return templates.TemplateResponse(
        request,
        "partials/arrivals.html",
        {"stop_id": stop_id, "arrivals": arrivals_for(conn, live, stop_id, at)},
    )


# search_routes puts the line name inside a regex, so only letters and digits
LINE_NAME_PATTERN = "^[0-9A-Za-z]{1,10}$"
LINE_NAME = re.compile(LINE_NAME_PATTERN)
LineQ = Annotated[str, Query(pattern=LINE_NAME_PATTERN)]


@app.get("/api/v1/routes/search", response_model=list[Route])
def routes_by_query(q: LineQ, conn: Conn):
    return search_routes(conn, q)


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
