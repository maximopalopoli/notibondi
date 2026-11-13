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
from notibondi.realtime import collect_stops_by_route
from notibondi.schedules import BUENOS_AIRES
from notibondi.worker import (
    OFF_PEAK_SECONDS,
    PEAK_SECONDS,
    LiveFeed,
    refresh_forever,
    refresh_seconds,
)

FEED_BYTES = (Path(__file__).parent / "fixtures" / "trip_updates_205.pb").read_bytes()


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


def responses(*statuses: int):
    """A fake GCBA that answers each request with the next status in order.

    200 sends the real feed sample. After the list ends, it keeps sending 500.
    """
    calls = []

    def handler(request):
        status = statuses[len(calls)] if len(calls) < len(statuses) else 500
        calls.append(status)
        content = FEED_BYTES if status == 200 else b""
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
    assert "feed refresh failed" in messages
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
