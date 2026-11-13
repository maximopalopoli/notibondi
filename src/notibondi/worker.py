import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from httpx2 import AsyncClient
from pydantic import BaseModel

from notibondi.config import Settings
from notibondi.gcba import fetch_trip_updates
from notibondi.realtime import LiveArrival, build_index
from notibondi.schedules import now

PEAK_SECONDS = 30
OFF_PEAK_SECONDS = 60
# Weekday rush hours in Buenos Aires: [start, end) in local hours.
PEAK_HOURS = [(7, 10), (17, 20)]

MAX_FEED_AGE_SECONDS = 5 * 60


def refresh_seconds(at: datetime) -> int:
    if at.weekday() < 5 and any(start <= at.hour < end for start, end in PEAK_HOURS):
        return PEAK_SECONDS
    return OFF_PEAK_SECONDS


log = logging.getLogger(__name__)


@dataclass
class LiveFeed:
    index: dict[str, list[LiveArrival]] = field(default_factory=dict)
    fetched_at: float | None = None  # time.monotonic() of the last good feed


async def refresh_forever(
    live: LiveFeed,
    client: AsyncClient,
    settings: Settings,
    lines_by_stop: dict[str, set[str]],
):
    while True:
        try:
            feed = await fetch_trip_updates(client, settings)

            # Note here we replace the index, avoiding handling mutexes
            index = await asyncio.to_thread(build_index, feed, lines_by_stop)
        except Exception:  # the loop must never die
            log.exception("feed refresh failed")
        else:
            live.index = index
            live.fetched_at = time.monotonic()
            log.info("feed refreshed: %d stops", len(index))
        await asyncio.sleep(refresh_seconds(now()))


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    feed_age_seconds: int | None


def feed_health(live: LiveFeed) -> Health:
    if live.fetched_at is None:
        return Health(status="degraded", feed_age_seconds=None)
    age = time.monotonic() - live.fetched_at
    status = "ok" if age <= MAX_FEED_AGE_SECONDS else "degraded"
    return Health(status=status, feed_age_seconds=int(age))
