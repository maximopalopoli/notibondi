from typing import Annotated

from fastapi import FastAPI, Query

from notibondi.db import Conn
from notibondi.stops import NearbyStop, find_nearby_stops

app = FastAPI()


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
