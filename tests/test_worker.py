import asyncio
import contextlib
import logging
from datetime import datetime
from pathlib import Path

import httpx2
import pytest
from google.transit import gtfs_realtime_pb2

from notibondi import worker
from notibondi.config import Settings
from notibondi.gcba import GcbaError
from notibondi.realtime import Vehicle, collect_stops_by_route
from notibondi.schedules import BUENOS_AIRES
from notibondi.worker import (
    OFF_PEAK_SECONDS,
    PEAK_SECONDS,
    LiveFeed,
    poll_forever,
    refresh_forever,
    refresh_route_names_forever,
    refresh_seconds,
    refresh_vehicles_forever,
    retry_seconds,
    vehicles_geojson,
)

FIXTURES = Path(__file__).parent / "fixtures"
FEED_BYTES = (FIXTURES / "trip_updates_205.pb").read_bytes()
VEHICLES_BYTES = (FIXTURES / "vehicle_positions_205.pb").read_bytes()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings():
    return Settings(
        database_url="postgresql+psycopg://unused",
        gcba_client_id="the-id",
        gcba_client_secret="the-secret",
        gcba_base_url="https://gcba.test",
    )


@pytest.fixture
def lines_by_stop():
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(FEED_BYTES)
    return {stop: {"108A"} for stop in collect_stops_by_route(feed)["205"]}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    # The real loop sleeps 30-60 s between downloads; the tests don't wait.
    monkeypatch.setattr(worker, "refresh_seconds", lambda at: 0)


def responses(*statuses: int, body: bytes = FEED_BYTES):
    """A fake GCBA that answers each request with the next status in order.

    200 sends body (the tripUpdates sample by default). After the list ends,
    it keeps sending 500.
    """
    calls = []

    def handler(request):
        status = statuses[len(calls)] if len(calls) < len(statuses) else 500
        calls.append(status)
        content = body if status == 200 else b""
        return httpx2.Response(status, content=content)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return client, calls


async def run_until(coro, condition, timeout: float = 2):
    """Run the worker until condition() is true, then cancel it."""
    task = asyncio.create_task(coro)
    try:
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(0.001)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return task


# refresh_seconds


def at(weekday_day: int, hour: int, minute: int = 0) -> datetime:
    # November 2026: the 16th is a Monday, the 21st a Saturday.
    return datetime(2026, 11, weekday_day, hour, minute, tzinfo=BUENOS_AIRES)


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (at(16, 8), PEAK_SECONDS),  # Monday morning rush
        (at(20, 18, 30), PEAK_SECONDS),  # Friday evening rush
        (at(16, 7), PEAK_SECONDS),  # the start hour is inside
        (at(16, 10), OFF_PEAK_SECONDS),  # the end hour is outside
        (at(16, 6, 59), OFF_PEAK_SECONDS),
        (at(16, 13), OFF_PEAK_SECONDS),  # midday
        (at(16, 2), OFF_PEAK_SECONDS),  # night
        (at(21, 8), OFF_PEAK_SECONDS),  # Saturday at a weekday rush hour
        (at(22, 18), OFF_PEAK_SECONDS),  # Sunday
    ],
)
def test_refresh_seconds(when, expected):
    # The autouse fixture replaces worker.refresh_seconds, not this import.
    assert refresh_seconds(when) == expected


# retry_seconds


@pytest.mark.parametrize(
    ("failures", "expected"),
    [
        (0, 60),  # no failure: the normal wait
        (1, 5),
        (2, 10),
        (3, 20),
        (4, 40),
        (5, 60),  # 80 would pass the interval
        (1000, 60),  # a long outage stays at the interval
    ],
)
def test_retry_seconds(failures, expected):
    assert retry_seconds(failures, interval=60) == expected


def test_retry_seconds_never_waits_more_than_a_short_interval():
    assert retry_seconds(4, interval=30) == 30


# poll_forever


class Stop(Exception):
    """Raised by the fake sleep to end poll_forever after some rounds."""


def fake_sleep(rounds: int):
    """A sleep that records each wait and stops the loop after `rounds`."""
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
        if len(waits) >= rounds:
            raise Stop

    return sleep, waits


def refresh_that(*works: bool):
    """A refresh that succeeds or fails in this order, then keeps failing."""
    calls = []

    async def refresh():
        ok = works[len(calls)] if len(calls) < len(works) else False
        calls.append(ok)
        if not ok:
            raise GcbaError("the GCBA is down")

    return refresh, calls


@pytest.mark.anyio
async def test_poll_forever_waits_the_interval_after_each_success():
    sleep, waits = fake_sleep(rounds=3)
    refresh, _ = refresh_that(True, True, True)

    with pytest.raises(Stop):
        await poll_forever("test", refresh, lambda: 60, sleep)

    assert waits == [60, 60, 60]


@pytest.mark.anyio
async def test_poll_forever_asks_the_interval_every_round():
    # refresh_seconds changes at rush hour, so the loop must not keep the first one
    sleep, waits = fake_sleep(rounds=3)
    refresh, _ = refresh_that(True, True, True)
    intervals = iter([30, 30, 60])

    with pytest.raises(Stop):
        await poll_forever("test", refresh, lambda: next(intervals), sleep)

    assert waits == [30, 30, 60]


@pytest.mark.anyio
async def test_poll_forever_backs_off_while_failing():
    sleep, waits = fake_sleep(rounds=7)
    refresh, calls = refresh_that()  # always fails

    with pytest.raises(Stop):
        await poll_forever("test", refresh, lambda: 60, sleep)

    assert waits == [5, 10, 20, 40, 60, 60, 60]
    assert len(calls) == 7  # it kept trying


@pytest.mark.anyio
async def test_poll_forever_success_resets_the_backoff():
    sleep, waits = fake_sleep(rounds=5)
    refresh, _ = refresh_that(False, False, True, False, True)

    with pytest.raises(Stop):
        await poll_forever("test", refresh, lambda: 60, sleep)

    assert waits == [5, 10, 60, 5, 60]


@pytest.mark.anyio
async def test_poll_forever_logs_a_gcba_failure_in_one_line(caplog):
    sleep, _ = fake_sleep(rounds=1)
    refresh, _ = refresh_that(False)

    with (
        caplog.at_level(logging.WARNING, logger="notibondi.worker"),
        pytest.raises(Stop),
    ):
        await poll_forever("vehicle positions", refresh, lambda: 60, sleep)

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "vehicle positions refresh failed: the GCBA is down"
    assert record.exc_info is None  # no traceback


@pytest.mark.anyio
async def test_poll_forever_logs_an_unexpected_error_with_its_traceback(caplog):
    sleep, _ = fake_sleep(rounds=1)

    async def buggy_refresh():
        raise KeyError("boom")

    with (
        caplog.at_level(logging.WARNING, logger="notibondi.worker"),
        pytest.raises(Stop),
    ):
        await poll_forever("trip updates", buggy_refresh, lambda: 60, sleep)

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert record.getMessage() == "trip updates refresh failed"
    assert record.exc_info is not None


# refresh_forever


@pytest.mark.anyio
async def test_a_good_download_fills_the_index(settings, lines_by_stop):
    live = LiveFeed()
    client, _ = responses(200)

    async with client:
        await run_until(
            refresh_forever(live, client, settings, lines_by_stop),
            lambda: live.fetched_at is not None,
        )

    assert live.index["20724"]
    assert all(a.line == "108A" for a in live.index["20724"])


@pytest.mark.anyio
async def test_a_good_download_also_stores_the_resolved_lines(settings, lines_by_stop):
    live = LiveFeed()
    client, _ = responses(200)

    async with client:
        await run_until(
            refresh_forever(live, client, settings, lines_by_stop),
            lambda: live.fetched_at is not None,
        )

    assert live.lines == {"205": "108A"}


@pytest.mark.anyio
async def test_a_failure_keeps_the_last_good_index(settings, lines_by_stop):
    live = LiveFeed()
    client, calls = responses(200, 500, 500)
    first_good = {}

    def two_failures_done():
        if live.fetched_at is not None and not first_good:
            first_good.update(index=live.index, fetched_at=live.fetched_at)
        # The 4th request starts only after the 2nd 500 was handled.
        return len(calls) >= 4

    async with client:
        await run_until(
            refresh_forever(live, client, settings, lines_by_stop),
            two_failures_done,
        )

    assert live.index is first_good["index"]
    assert live.fetched_at == first_good["fetched_at"]


@pytest.mark.anyio
async def test_fetched_at_only_moves_on_a_good_download(settings, lines_by_stop):
    live = LiveFeed()
    client, calls = responses(200, 500, 200)
    seen = set()

    def third_done():
        if live.fetched_at is not None:
            seen.add(live.fetched_at)
        return len(calls) >= 4

    async with client:
        await run_until(
            refresh_forever(live, client, settings, lines_by_stop), third_done
        )

    assert len(seen) == 2  # one per 200, none for the 500


@pytest.mark.anyio
async def test_the_loop_logs_failures_and_keeps_going(settings, lines_by_stop, caplog):
    live = LiveFeed()
    client, _ = responses(500, 200)

    with caplog.at_level(logging.INFO, logger="notibondi.worker"):
        async with client:
            await run_until(
                refresh_forever(live, client, settings, lines_by_stop),
                lambda: live.fetched_at is not None,
            )

    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("trip updates refresh failed: ") for m in messages)
    assert any(m.startswith("feed refreshed:") for m in messages)


@pytest.mark.anyio
async def test_the_loop_survives_an_unexpected_error(
    settings, lines_by_stop, monkeypatch
):
    # Not a GcbaError: a bug in build_index must not kill the worker either.
    real_build_index = worker.build_index
    attempts = []

    def flaky_build_index(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise KeyError("boom")
        return real_build_index(*args)

    monkeypatch.setattr(worker, "build_index", flaky_build_index)
    live = LiveFeed()
    client, _ = responses(200, 200)

    async with client:
        await run_until(
            refresh_forever(live, client, settings, lines_by_stop),
            lambda: live.fetched_at is not None,
        )

    assert len(attempts) == 2
    assert live.index["20724"]


@pytest.mark.anyio
async def test_cancel_stops_the_loop(settings, lines_by_stop):
    live = LiveFeed()
    client, calls = responses(200)

    async with client:
        task = await run_until(
            refresh_forever(live, client, settings, lines_by_stop),
            lambda: len(calls) >= 1,
        )

    assert task.cancelled()


# refresh_vehicles_forever


@pytest.fixture
def no_waiting_for_vehicles(monkeypatch):
    monkeypatch.setattr(worker, "VEHICLES_SECONDS", 0)


@pytest.mark.anyio
async def test_a_good_download_fills_the_vehicles(settings, no_waiting_for_vehicles):
    live = LiveFeed()
    client, _ = responses(200, body=VEHICLES_BYTES)

    async with client:
        await run_until(
            refresh_vehicles_forever(live, client, settings),
            lambda: live.vehicles_at is not None,
        )

    assert list(live.vehicles) == ["205"]
    assert len(live.vehicles["205"]) == 11


@pytest.mark.anyio
async def test_a_failure_keeps_the_last_good_vehicles(
    settings, no_waiting_for_vehicles
):
    live = LiveFeed()
    client, calls = responses(200, 500, 500, body=VEHICLES_BYTES)
    first_good = {}

    def two_failures_done():
        if live.vehicles_at is not None and not first_good:
            first_good.update(vehicles=live.vehicles, at=live.vehicles_at)
        return len(calls) >= 4

    async with client:
        await run_until(
            refresh_vehicles_forever(live, client, settings), two_failures_done
        )

    assert live.vehicles is first_good["vehicles"]
    assert live.vehicles_at == first_good["at"]


@pytest.mark.anyio
async def test_the_vehicles_loop_does_not_touch_the_arrivals(
    settings, no_waiting_for_vehicles
):
    live = LiveFeed()
    client, _ = responses(200, body=VEHICLES_BYTES)

    async with client:
        await run_until(
            refresh_vehicles_forever(live, client, settings),
            lambda: live.vehicles_at is not None,
        )

    assert live.index == {}
    assert live.fetched_at is None


@pytest.mark.anyio
async def test_cancel_stops_the_vehicles_loop(settings, no_waiting_for_vehicles):
    live = LiveFeed()
    client, calls = responses(200, body=VEHICLES_BYTES)

    async with client:
        task = await run_until(
            refresh_vehicles_forever(live, client, settings),
            lambda: len(calls) >= 1,
        )

    assert task.cancelled()


# refresh_route_names_forever


def names_client(*batches: list[dict]):
    """A fake vehiclePositionsSimple that sends each batch of buses in order."""
    calls = []

    def handler(request):
        if len(calls) >= len(batches):
            calls.append(500)
            return httpx2.Response(500)
        calls.append(200)
        return httpx2.Response(200, json=batches[len(calls) - 1])

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), calls


@pytest.fixture
def no_waiting_for_names(monkeypatch):
    monkeypatch.setattr(worker, "ROUTE_NAMES_SECONDS", 0)


@pytest.mark.anyio
async def test_a_good_download_fills_the_route_names(settings, no_waiting_for_names):
    live = LiveFeed()
    client, _ = names_client([{"route_id": "834", "route_short_name": "152"}])

    async with client:
        await run_until(
            refresh_route_names_forever(live, client, settings),
            lambda: live.route_names,
        )

    assert live.route_names == {"834": "152"}


@pytest.mark.anyio
async def test_route_names_add_up_between_downloads(settings, no_waiting_for_names):
    # 834 has no bus in the second download, but keeps its name
    live = LiveFeed()
    client, calls = names_client(
        [{"route_id": "834", "route_short_name": "152"}],
        [{"route_id": "1553", "route_short_name": "228B"}],
    )

    async with client:
        await run_until(
            refresh_route_names_forever(live, client, settings),
            lambda: len(calls) >= 3,
        )

    assert live.route_names == {"834": "152", "1553": "228B"}


@pytest.mark.anyio
async def test_the_arrivals_refresh_uses_the_route_names(settings, lines_by_stop):
    # Route 205 resolves to 108A by its stops; its name says otherwise
    live = LiveFeed(route_names={"205": "108B"})
    lines_by_stop = {**lines_by_stop, "X": {"108B"}}
    client, _ = responses(200)

    async with client:
        await run_until(
            refresh_forever(live, client, settings, lines_by_stop),
            lambda: live.fetched_at is not None,
        )

    assert live.lines == {"205": "108B"}


# vehicles_geojson

# The newest position in vehicle_positions_205.pb (2026-11-16, 08:55)
SAMPLE_NOW = 1794830100


@pytest.fixture
def live_108(settings):
    """A LiveFeed with the 108A sample: live route 205 resolves to 108A."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(VEHICLES_BYTES)
    return LiveFeed(lines={"205": "108A"}, vehicles=worker.group_vehicles(feed))


def bus(vehicle_id: str, timestamp: int = SAMPLE_NOW) -> Vehicle:
    return Vehicle(
        vehicle_id,
        lat=-34.6,
        lon=-58.4,
        timestamp=timestamp,
        label="x",
        direction_id=0,
    )


def test_vehicles_geojson_is_a_feature_collection(live_108):
    collection = vehicles_geojson(live_108, "108A", SAMPLE_NOW)

    assert collection["type"] == "FeatureCollection"
    assert len(collection["features"]) == 11


def test_vehicles_geojson_makes_one_point_per_bus(live_108):
    features = vehicles_geojson(live_108, "108A", SAMPLE_NOW)["features"]
    feature = next(f for f in features if f["id"] == "94843")

    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    # GeoJSON puts longitude first
    assert feature["geometry"]["coordinates"] == pytest.approx(
        [-58.3923416, -34.5912895]
    )
    assert feature["properties"] == {
        "label": "2429-4868",
        "timestamp": 1794830100,
        "direction_id": 0,
    }


def test_vehicles_geojson_drops_positions_older_than_5_minutes():
    live = LiveFeed(
        lines={"205": "108A"},
        vehicles={
            "205": [
                bus("fresh"),
                bus("limit", SAMPLE_NOW - 300),
                bus("old", SAMPLE_NOW - 301),
            ]
        },
    )

    features = vehicles_geojson(live, "108A", SAMPLE_NOW)["features"]

    assert [f["id"] for f in features] == ["fresh", "limit"]


def test_vehicles_geojson_joins_every_live_route_of_the_line():
    # 108A comes in the feed as two live routes, 205 and 206
    live = LiveFeed(
        lines={"205": "108A", "206": "108A", "311": "152A"},
        vehicles={"205": [bus("a")], "206": [bus("b")], "311": [bus("c")]},
    )

    features = vehicles_geojson(live, "108A", SAMPLE_NOW)["features"]

    assert sorted(f["id"] for f in features) == ["a", "b"]


def test_vehicles_geojson_is_empty_for_a_line_without_live_routes(live_108):
    assert vehicles_geojson(live_108, "152A", SAMPLE_NOW) == {
        "type": "FeatureCollection",
        "features": [],
    }


def test_vehicles_geojson_skips_a_live_route_without_positions():
    # lines and vehicles come from two feeds, so they may not have the same routes
    live = LiveFeed(lines={"205": "108A"}, vehicles={})

    assert vehicles_geojson(live, "108A", SAMPLE_NOW)["features"] == []
