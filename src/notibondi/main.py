from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from notibondi.db import Conn
from notibondi.stops import (
    MAX_RADIUS_M,
    MAX_SEARCH_LIMIT,
    NearbyStop,
    Stop,
    find_nearby_stops,
    search_stops,
)

app = FastAPI()

BASE_DIR = Path(__file__).parent

Lat = Annotated[float, Query(ge=-90, le=90)]
Lon = Annotated[float, Query(ge=-180, le=180)]
Radius = Annotated[int, Query(gt=0, le=MAX_RADIUS_M)]

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/health")
def health():
    return {"status": "ok"}


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
        request, "partials/nearby_stops.html", {"stops": stops}
    )


Q = Annotated[str, Query(min_length=2, max_length=100)]
Limit = Annotated[int, Query(gt=0, le=MAX_SEARCH_LIMIT)]


@app.get("/api/v1/stops/search", response_model=list[Stop])
def search_stops_api(q: Q, conn: Conn, limit: Limit = 20):
    return search_stops(conn, q, limit)
