import logging
import time
from pathlib import Path

from google.transit import gtfs_realtime_pb2

from notibondi.realtime import (
    build_index,
    collect_stops_by_route,
    group_vehicles,
    resolve_directions,
    routes_by_stop,
    unknown_branches,
)
from notibondi.worker import LiveFeed

log = logging.getLogger(__name__)


FIXTURES_DIR = Path(__file__).parents[2] / "tests" / "fixtures"


def load_fixtures(
    live: LiveFeed,
    lines_by_stop: dict[str, set[str]],
    directions_by_stop: dict[str, set[tuple[str, int]]] | None = None,
):
    static_lines = {line for lines in lines_by_stop.values() for line in lines}

    feed = read_trip_updates()
    shift_trip_timestamps(feed)
    names = live.route_names
    index, lines = build_index(feed, lines_by_stop, names)
    unknown = unknown_branches(names, lines, static_lines)
    live.index = index
    live.lines = lines
    live.unknown_branch = unknown
    live.routes_by_stop = routes_by_stop(feed)
    live.directions = resolve_directions(
        collect_stops_by_route(feed), directions_by_stop or {}, lines, unknown
    )
    live.fetched_at = time.monotonic()
    log.info("feed refreshed: %d stops", len(index))

    feed = read_vehicle_positions()
    shift_vehicle_timestamps(feed)
    vehicles = group_vehicles(feed)
    live.vehicles = vehicles
    live.vehicles_at = time.monotonic()
    log.info("vehicles refreshed: %d routes", len(vehicles))


def shift_trip_timestamps(feed: gtfs_realtime_pb2.FeedMessage):
    delta = int(time.time()) - feed.header.timestamp
    feed.header.timestamp += delta

    for entity in feed.entity:
        for stu in entity.trip_update.stop_time_update:
            if stu.arrival.time != 0:
                stu.arrival.time += delta


def shift_vehicle_timestamps(feed: gtfs_realtime_pb2.FeedMessage):
    newest = max(entity.vehicle.timestamp for entity in feed.entity)
    delta = int(time.time()) - newest
    for entity in feed.entity:
        entity.vehicle.timestamp += delta


def read_feed(path: Path) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(path.read_bytes())
    return feed


def read_trip_updates():
    feed_205 = read_feed(FIXTURES_DIR / "trip_updates_205.pb")
    feed_206 = read_feed(FIXTURES_DIR / "trip_updates_206.pb")
    feed_205.entity.extend(feed_206.entity)
    return feed_205


def read_vehicle_positions():
    return read_feed(FIXTURES_DIR / "vehicle_positions_205.pb")
