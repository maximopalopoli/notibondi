"""Record every AMBA bus position, once a minute, into SQLite.

Polls the whole GCBA vehiclePositions feed every POLL_SECONDS. Each row is one
report of one bus: with its trip and route_id when the feed has them, so the
positions of one vehicle_id with one trip_id draw that trip. That is what the
trace experiments of 2026-11-18 use to tell which line an unknown route_id
is, and where buses leave their 2021 route. The polls table records when we
were (and weren't) watching.

A bus whose position didn't change since its last stored row is skipped: at
night most buses are parked, and an hour of positions is ~50 MB already.

Usage: uv run python pilot/tracker.py [db_path]
"""

import logging
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2
from pydantic_settings import BaseSettings, SettingsConfigDict

POLL_SECONDS = 60
# Per socket operation, not for the whole download (~2 MB, sometimes slow)
TIMEOUT_SECONDS = 60
URL = "https://apitransporte.buenosaires.gob.ar/colectivos/vehiclePositions"
DEFAULT_DB = Path("data/track.sqlite")
# The feed also has Mar del Plata and other cities; keep the AMBA only.
LAT_RANGE = (-35.4, -34.0)
LON_RANGE = (-59.4, -57.7)

SCHEMA = """
CREATE TABLE IF NOT EXISTS polls (
    polled_at  INTEGER NOT NULL,
    feed_ts    INTEGER,
    ok         INTEGER NOT NULL,
    n_vehicles INTEGER,
    n_new      INTEGER,
    error      TEXT
);
CREATE TABLE IF NOT EXISTS pos (
    vehicle_id   TEXT NOT NULL,
    ts           INTEGER NOT NULL,
    route_id     TEXT NOT NULL,
    trip_id      TEXT NOT NULL,
    direction_id INTEGER,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    fetched_at   INTEGER NOT NULL,
    PRIMARY KEY (vehicle_id, ts)
) WITHOUT ROWID;
"""

INSERT = "INSERT OR IGNORE INTO pos VALUES (?, ?, ?, ?, ?, ?, ?, ?)"

log = logging.getLogger("tracker")


class Credentials(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcba_client_id: str
    gcba_client_secret: str


def fetch(creds: Credentials) -> gtfs_realtime_pb2.FeedMessage:
    query = urlencode(
        {
            "client_id": creds.gcba_client_id,
            "client_secret": creds.gcba_client_secret,
        }
    )
    with urlopen(f"{URL}?{query}", timeout=TIMEOUT_SECONDS) as resp:
        body = resp.read()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(body)
    return feed


def position_rows(feed: gtfs_realtime_pb2.FeedMessage, fetched_at: int):
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        lat, lon = v.position.latitude, v.position.longitude
        if not (
            LAT_RANGE[0] < lat < LAT_RANGE[1] and LON_RANGE[0] < lon < LON_RANGE[1]
        ):
            continue
        # About 30% of the buses come without a trip: no route_id, no trip_id
        has_trip = v.HasField("trip")
        yield (
            v.vehicle.id,
            v.timestamp,
            v.trip.route_id if has_trip else "",
            v.trip.trip_id if has_trip else "",
            v.trip.direction_id if has_trip else None,
            lat,
            lon,
            fetched_at,
        )


def moved(rows, last: dict[str, tuple[float, float]]):
    """Keep the rows whose bus is somewhere new, and remember where it is."""
    for row in rows:
        vehicle_id, lat, lon = row[0], row[5], row[6]
        if last.get(vehicle_id) == (lat, lon):
            continue
        last[vehicle_id] = (lat, lon)
        yield row


def poll(
    db: sqlite3.Connection,
    creds: Credentials,
    last_feed_ts: list[int | None],
    last_pos: dict[str, tuple[float, float]],
):
    now = int(time.time())
    try:
        feed = fetch(creds)
    # URLError, HTTPError and timeouts are OSErrors; keep running on any of them.
    except (OSError, DecodeError) as exc:
        log.warning("vehiclePositions: %s", exc)
        with db:
            db.execute(
                "INSERT INTO polls VALUES (?, NULL, 0, NULL, NULL, ?)",
                (now, f"{type(exc).__name__}: {exc}"),
            )
        return

    feed_ts = feed.header.timestamp or None
    rows = list(position_rows(feed, now))
    n_new = 0
    # Same header timestamp means the feed wasn't refreshed: nothing new.
    if feed_ts is None or last_feed_ts[0] != feed_ts:
        with db:
            n_new = db.executemany(INSERT, moved(rows, last_pos)).rowcount
    last_feed_ts[0] = feed_ts
    with db:
        db.execute(
            "INSERT INTO polls VALUES (?, ?, 1, ?, ?, NULL)",
            (now, feed_ts, len(rows), n_new),
        )
    log.info("%d buses, %d new rows, feed_ts %s", len(rows), n_new, feed_ts)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    creds = Credentials()
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    log.info("recording every AMBA bus into %s", db_path)

    last_feed_ts: list[int | None] = [None]
    last_pos: dict[str, tuple[float, float]] = {}
    try:
        while True:
            started = time.monotonic()
            poll(db, creds, last_feed_ts, last_pos)
            time.sleep(max(0, POLL_SECONDS - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        db.close()


if __name__ == "__main__":
    main()
