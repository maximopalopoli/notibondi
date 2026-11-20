import contextlib
import time

import pytest
from google.transit import gtfs_realtime_pb2

from notibondi import main
from notibondi.config import Settings
from notibondi.fixtures import (
    load_fixtures,
    read_trip_updates,
    read_vehicle_positions,
    shift_trip_timestamps,
    shift_vehicle_timestamps,
)
from notibondi.realtime import collect_stops_by_route
from notibondi.worker import LiveFeed, vehicles_geojson


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def lines_by_stop():
    """Every stop of the two 108 fixtures (live routes 205 and 206) is 108A."""
    stops_by_route = collect_stops_by_route(read_trip_updates())
    return {stop: {"108A"} for stops in stops_by_route.values() for stop in stops}


def vehicle_times(feed):
    return [entity.vehicle.timestamp for entity in feed.entity]


def arrival_times(feed):
    return [
        stu.arrival.time
        for entity in feed.entity
        for stu in entity.trip_update.stop_time_update
    ]


# --- shift_vehicle_timestamps ---


def test_vehicle_shift_moves_the_newest_bus_to_now():
    feed = read_vehicle_positions()
    before = int(time.time())
    shift_vehicle_timestamps(feed)
    after = int(time.time())

    assert before <= max(vehicle_times(feed)) <= after


def test_vehicle_shift_keeps_the_gaps_between_buses():
    old = vehicle_times(read_vehicle_positions())
    feed = read_vehicle_positions()
    shift_vehicle_timestamps(feed)
    new = vehicle_times(feed)

    assert [n - o for n, o in zip(new, old)] == [new[0] - old[0]] * len(old)


# --- shift_trip_timestamps ---


def test_trip_shift_moves_the_download_time_to_now():
    feed = read_trip_updates()
    before = int(time.time())
    shift_trip_timestamps(feed)
    after = int(time.time())

    assert before <= feed.header.timestamp <= after


def test_trip_shift_keeps_the_seconds_left_to_each_arrival():
    """A bus 5 min away when the feed was recorded is 5 min away now."""
    old = read_trip_updates()
    old_left = [t - old.header.timestamp for t in arrival_times(old) if t]
    feed = read_trip_updates()
    shift_trip_timestamps(feed)
    new_left = [t - feed.header.timestamp for t in arrival_times(feed) if t]

    assert new_left == old_left


def test_trip_shift_leaves_missing_arrivals_alone():
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_000_000
    update = feed.entity.add(id="1").trip_update
    update.trip.trip_id = "t1"
    with_time = update.stop_time_update.add(stop_id="a")
    with_time.arrival.time = 1_000_300
    update.stop_time_update.add(stop_id="b")  # NO_DATA: no arrival

    shift_trip_timestamps(feed)

    a, b = feed.entity[0].trip_update.stop_time_update
    assert a.arrival.time == feed.header.timestamp + 300
    assert not b.HasField("arrival")
    assert b.arrival.time == 0


# --- load_fixtures ---


def test_load_fixtures_gives_the_108a_live_buses_and_arrivals(lines_by_stop):
    live = LiveFeed()
    load_fixtures(live, lines_by_stop)

    assert set(live.lines.values()) == {"108A"}
    assert live.index
    assert live.fetched_at is not None
    assert live.vehicles_at is not None
    # The whole point of the shift: without it, every bus is too old to show
    assert vehicles_geojson(live, "108A", time.time())["features"]


def test_load_fixtures_has_arrivals_in_the_future(lines_by_stop):
    live = LiveFeed()
    load_fixtures(live, lines_by_stop)

    now = time.time()
    arrivals = [a for arrivals in live.index.values() for a in arrivals]
    assert any(a.arrival_time > now for a in arrivals)


# --- lifespan ---


class FakeEngine:
    def connect(self):
        return contextlib.nullcontext(None)


@pytest.fixture
def started(monkeypatch, lines_by_stop):
    """Start the lifespan in a mode; it records which workers were started.

    The DB is faked, and the workers are replaced by ones that only record
    their name, so nothing reaches the GCBA even in "gcba" mode.
    """
    workers = []

    def fake_worker(name):
        async def run(*args):
            workers.append(name)

        return run

    monkeypatch.setattr(main, "get_engine", FakeEngine)
    monkeypatch.setattr(main, "load_lines_by_stop", lambda conn: lines_by_stop)
    monkeypatch.setattr(main, "load_directions_by_stop", lambda conn: {})
    monkeypatch.setattr(main, "load_route_names", lambda conn: {})
    monkeypatch.setattr(main, "refresh_forever", fake_worker("trips"))
    monkeypatch.setattr(main, "refresh_vehicles_forever", fake_worker("vehicles"))
    monkeypatch.setattr(main, "refresh_route_names_forever", fake_worker("route names"))

    @contextlib.asynccontextmanager
    async def start(mode):
        settings = Settings(
            database_url="postgresql+psycopg://unused",
            gcba_client_id="the-id",
            gcba_client_secret="the-secret",
            live_feeds=mode,
        )
        monkeypatch.setattr(main, "get_settings", lambda: settings)
        async with main.lifespan(main.app):
            await main.asyncio.sleep(0)  # let the started tasks run once
            yield main.app.state.live, workers

    return start


@pytest.mark.anyio
async def test_gcba_mode_starts_the_three_workers(started):
    async with started("gcba") as (_, workers):
        assert sorted(workers) == ["route names", "trips", "vehicles"]


@pytest.mark.anyio
async def test_off_mode_starts_no_workers_and_has_no_live_data(started):
    async with started("off") as (live, workers):
        assert workers == []
        assert live.index == {}
        assert live.vehicles == {}


@pytest.mark.anyio
async def test_fixtures_mode_starts_no_workers_but_has_live_data(started):
    async with started("fixtures") as (live, workers):
        assert workers == []
        assert vehicles_geojson(live, "108A", time.time())["features"]


def test_live_feeds_defaults_to_gcba(monkeypatch):
    # Not from the developer's .env, which may say LIVE_FEEDS=fixtures
    monkeypatch.delenv("LIVE_FEEDS", raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused",
        gcba_client_id="the-id",
        gcba_client_secret="the-secret",
    )
    assert settings.live_feeds == "gcba"


def test_load_fixtures_uses_the_overrides_of_the_live_feed(lines_by_stop):
    # Route 205 is a 108A by its stops (108B stops at only one of them),
    # and route_overrides.csv would win
    lines_by_stop = dict(lines_by_stop)
    lines_by_stop[min(lines_by_stop)] = {"108A", "108B"}
    live = LiveFeed(overrides={"205": "108B"})

    load_fixtures(live, lines_by_stop)

    assert live.lines["205"] == "108B"
