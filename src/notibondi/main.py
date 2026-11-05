from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from notibondi.db import Conn
from notibondi.stops import NearbyStop, find_nearby_stops

app = FastAPI()

BASE_DIR = Path(__file__).parent

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/stops/nearby", response_model=list[NearbyStop])
def nearby_stops(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    conn: Conn,
    radius: Annotated[int, Query(gt=0, le=1500)] = 400,
):
    return find_nearby_stops(conn, lat, lon, radius)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")
