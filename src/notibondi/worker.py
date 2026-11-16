import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from httpx2 import AsyncClient
from pydantic import BaseModel

from notibondi.config import Settings
from notibondi.gcba import fetch_trip_updates
from notibondi.realtime import LiveArrival, Vehicle, build_index
from notibondi.schedules import now

PEAK_SECONDS = 30
OFF_PEAK_SECONDS = 60
# Weekday rush hours in Buenos Aires: [start, end) in local hours.
PEAK_HOURS = [(7, 10), (17, 20)]

# After a failed download, retry after 5 s, then 10, 20, 40… (see retry_seconds)
FIRST_RETRY_SECONDS = 5

MAX_FEED_AGE_SECONDS = 5 * 60


def refresh_seconds(at: datetime) -> int:
    if at.weekday() < 5 and any(start <= at.hour < end for start, end in PEAK_HOURS):
        return PEAK_SECONDS
    return OFF_PEAK_SECONDS


def retry_seconds(failures: int, interval: int) -> int:
    """How long to wait after `failures` failed downloads in a row.

    0 failures is the normal wait. Then it doubles from FIRST_RETRY_SECONDS,
    but never goes above the normal interval.
    """
    if failures == 0:
        return interval
    return min(FIRST_RETRY_SECONDS * 2 ** (failures - 1), interval)


log = logging.getLogger(__name__)


@dataclass
class LiveFeed:
    index: dict[str, list[LiveArrival]] = field(default_factory=dict)
    fetched_at: float | None = None  # time.monotonic() of the last good feed
    vehicles: dict[str, list[Vehicle]] = field(default_factory=dict)
    vehicles_at: float | None = None
    lines: dict[str, str] = field(default_factory=dict)


async def poll_forever(
    name: str,
    refresh: Callable[[], Awaitable[None]],
    interval: Callable[[], int],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Call refresh() forever, waiting less after a failure.

    refresh downloads, processes and stores one feed; if it raises, nothing
    was stored, so the last good data stays. Only cancelling the task ends
    the loop. The tests pass a fake sleep, so they don't really wait.
    """
    failures = 0
    while True:
        try:
            await refresh()
        except Exception:  # the loop must never die
            failures += 1
            log.exception("%s refresh failed", name)
        else:
            failures = 0
        await sleep(retry_seconds(failures, interval()))


async def refresh_forever(
    live: LiveFeed,
    client: AsyncClient,
    settings: Settings,
    lines_by_stop: dict[str, set[str]],
):
    async def refresh():
        feed = await fetch_trip_updates(client, settings)
        index = await asyncio.to_thread(build_index, feed, lines_by_stop)
        # Only reached if both lines above worked. Replacing the whole index
        # in one step means readers see the old one or the new one, no lock.
        live.index = index
        live.fetched_at = time.monotonic()
        log.info("feed refreshed: %d stops", len(index))

    await poll_forever("trip updates", refresh, lambda: refresh_seconds(now()))


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    feed_age_seconds: int | None


def feed_health(live: LiveFeed) -> Health:
    if live.fetched_at is None:
        return Health(status="degraded", feed_age_seconds=None)
    age = time.monotonic() - live.fetched_at
    status = "ok" if age <= MAX_FEED_AGE_SECONDS else "degraded"
    return Health(status=status, feed_age_seconds=int(age))
