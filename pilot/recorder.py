"""Record realtime arrival predictions for a few routes into SQLite.

Polls GCBA tripUpdates filtered by route every POLL_SECONDS and keeps the last
prediction for each (trip, service day, stop). When a stop drops out of the
feed the bus has passed it, so the last prediction approximates the real
arrival. The polls table records when we were (and weren't) watching.

Usage: uv run --group pilot python pilot/recorder.py [db_path]
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

# Realtime route_ids for line 108 (Retiro - Liniers - V. Madero); they don't
# match the static GTFS ids. The feed's headsigns ("a Belgrano (CABA)") are off.
ROUTES = {"205": "108 Retiro -> Liniers/V. Madero", "206": "108 Liniers -> Retiro"}
POLL_SECONDS = 60
TIMEOUT_SECONDS = 15
URL = "https://apitransporte.buenosaires.gob.ar/colectivos/tripUpdates"
DEFAULT_DB = Path("data/pilot.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS polls (
    polled_at INTEGER NOT NULL,
    feed_ts   INTEGER,
    route_id  TEXT NOT NULL,
    ok        INTEGER NOT NULL,
    n_trips   INTEGER,
    error     TEXT
);
CREATE TABLE IF NOT EXISTS arrivals (
    trip_id       TEXT NOT NULL,
    start_date    TEXT NOT NULL,
    stop_id       TEXT NOT NULL,
    route_id      TEXT NOT NULL,
    start_time    TEXT,
    stop_sequence INTEGER,
    vehicle_id    TEXT,
    predicted_at  INTEGER NOT NULL,
    delay         INTEGER,
    first_seen    INTEGER NOT NULL,
    last_seen     INTEGER NOT NULL,
    PRIMARY KEY (trip_id, start_date, stop_id)
);
"""

UPSERT = """
INSERT INTO arrivals VALUES (
    :trip_id, :start_date, :stop_id, :route_id, :start_time, :stop_sequence,
    :vehicle_id, :predicted_at, :delay, :now, :now
)
ON CONFLICT (trip_id, start_date, stop_id) DO UPDATE SET
    predicted_at = excluded.predicted_at,
    delay = excluded.delay,
    vehicle_id = excluded.vehicle_id,
    last_seen = excluded.last_seen
"""

log = logging.getLogger("recorder")


class Credentials(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcba_client_id: str
    gcba_client_secret: str


def fetch(creds: Credentials, route_id: str) -> gtfs_realtime_pb2.FeedMessage:
    query = urlencode(
        {
            "client_id": creds.gcba_client_id,
            "client_secret": creds.gcba_client_secret,
            "route_id": route_id,
        }
    )
    with urlopen(f"{URL}?{query}", timeout=TIMEOUT_SECONDS) as resp:
        body = resp.read()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(body)
    return feed


def arrival_rows(feed: gtfs_realtime_pb2.FeedMessage, route_id: str, now: int):
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        # The filter is server-side; skip anything else defensively.
        if tu.trip.route_id != route_id:
            continue
        for stu in tu.stop_time_update:
            if not stu.HasField("arrival") or not stu.arrival.time:
                continue
            yield {
                "trip_id": tu.trip.trip_id,
                "start_date": tu.trip.start_date,
                "stop_id": stu.stop_id,
                "route_id": route_id,
                "start_time": tu.trip.start_time,
                "stop_sequence": stu.stop_sequence,
                "vehicle_id": tu.vehicle.id or None,
                "predicted_at": stu.arrival.time,
                "delay": stu.arrival.delay if stu.arrival.HasField("delay") else None,
                "now": now,
            }


def poll(db: sqlite3.Connection, creds: Credentials, last_feed_ts: dict[str, int]):
    for route_id in ROUTES:
        now = int(time.time())
        try:
            feed = fetch(creds, route_id)
        # URLError, HTTPError and timeouts are OSErrors; keep running on any of them.
        except (OSError, DecodeError) as exc:
            log.warning("route %s: %s", route_id, exc)
            with db:
                db.execute(
                    "INSERT INTO polls VALUES (?, NULL, ?, 0, NULL, ?)",
                    (now, route_id, f"{type(exc).__name__}: {exc}"),
                )
            continue

        feed_ts = feed.header.timestamp or None
        n_trips = sum(1 for e in feed.entity if e.HasField("trip_update"))
        with db:
            db.execute(
                "INSERT INTO polls VALUES (?, ?, ?, 1, ?, NULL)",
                (now, feed_ts, route_id, n_trips),
            )
            # Same header timestamp means the feed wasn't refreshed: nothing new.
            if feed_ts is None or last_feed_ts.get(route_id) != feed_ts:
                db.executemany(UPSERT, arrival_rows(feed, route_id, now))
        last_feed_ts[route_id] = feed_ts
        log.info("route %s: %d trips, feed_ts %s", route_id, n_trips, feed_ts)


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
    # Databases from before the error column was added
    if "error" not in {row[1] for row in db.execute("PRAGMA table_info(polls)")}:
        db.execute("ALTER TABLE polls ADD COLUMN error TEXT")
    log.info("recording %s into %s", ", ".join(ROUTES), db_path)

    last_feed_ts: dict[str, int] = {}
    try:
        while True:
            started = time.monotonic()
            poll(db, creds, last_feed_ts)
            time.sleep(max(0, POLL_SECONDS - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        db.close()


if __name__ == "__main__":
    main()
