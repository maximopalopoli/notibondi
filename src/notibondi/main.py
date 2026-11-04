from fastapi import FastAPI

from notibondi.db import Conn
from notibondi.stops import NearbyStop, find_nearby_stops

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/stops/nearby", response_model=list[NearbyStop])
def nearby_stops(
    lat: float,
    lon: float,
    conn: Conn,
    radius: int = 400,
):
    return find_nearby_stops(conn, lat, lon, radius)
