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
from notibondi.gcba import (
    GcbaError,
    fetch_route_names,
    fetch_trip_updates,
    fetch_vehicle_positions,
)
from notibondi.realtime import LiveArrival, Vehicle, build_index, group_vehicles
from notibondi.schedules import now

PEAK_SECONDS = 30
OFF_PEAK_SECONDS = 60
# Weekday rush hours in Buenos Aires: [start, end) in local hours.
PEAK_HOURS = [(7, 10), (17, 20)]

# The positions change once a minute, at rush hour too (measured 2026-11-16)
VEHICLES_SECONDS = 60

# A route_id keeps its name, and that feed is slow (~23 s)
ROUTE_NAMES_SECONDS = 10 * 60

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
    vehicles_at: float | None = None  # time.monotonic() of the last good positions
    lines: dict[str, str] = field(default_factory=dict)
    # Every name seen since startup, by live route_id (see fetch_route_names)
    route_names: dict[str, str] = field(default_factory=dict)


MAX_VEHICLE_AGE_SECONDS = 60 * 5


def vehicles_geojson(live: LiveFeed, line: str, now: float) -> dict:
    features = []
    for live_route_id, name in live.lines.items():
        if name != line:
            continue
        for v in live.vehicles.get(live_route_id, []):
            if now - v.timestamp > MAX_VEHICLE_AGE_SECONDS:
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": v.vehicle_id,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [v.lon, v.lat],
                    },
                    "properties": {
                        "label": v.label,
                        "timestamp": v.timestamp,
                        "direction_id": v.direction_id,
                    },
                }
            )
    return {"type": "FeatureCollection", "features": features}


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
        except GcbaError as e:
            # Expected: the GCBA fails every day. One line, no traceback.
            failures += 1
            log.warning("%s refresh failed: %s", name, e)
        except Exception:  # a bug: the traceback helps, but the loop must never die
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
        index, lines = await asyncio.to_thread(
            build_index, feed, lines_by_stop, live.route_names
        )
        # Only reached if both lines above worked. Replacing the whole index
        # in one step means readers see the old one or the new one, no lock.
        live.index = index
        live.lines = lines
        live.fetched_at = time.monotonic()
        log.info("feed refreshed: %d stops", len(index))

    await poll_forever("trip updates", refresh, lambda: refresh_seconds(now()))


async def refresh_vehicles_forever(
    live: LiveFeed,
    client: AsyncClient,
    settings: Settings,
):
    async def refresh():
        feed = await fetch_vehicle_positions(client, settings)
        vehicles = await asyncio.to_thread(group_vehicles, feed)
        live.vehicles = vehicles
        live.vehicles_at = time.monotonic()
        log.info("vehicles refreshed: %d routes", len(vehicles))

    await poll_forever("vehicle positions", refresh, lambda: VEHICLES_SECONDS)


async def refresh_route_names_forever(
    live: LiveFeed,
    client: AsyncClient,
    settings: Settings,
):
    async def refresh():
        names = await fetch_route_names(client, settings)
        # Added to the old ones, not replacing them: the feed only has the
        # route_ids with a bus right now. The next arrivals refresh uses them.
        live.route_names = {**live.route_names, **names}
        log.info("route names refreshed: %d known", len(live.route_names))

    await poll_forever("route names", refresh, lambda: ROUTE_NAMES_SECONDS)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    feed_age_seconds: int | None
    # Only informative: old positions break the map, not the arrivals
    vehicles_age_seconds: int | None = None


def age_seconds(at: float | None) -> int | None:
    return None if at is None else int(time.monotonic() - at)


def feed_health(live: LiveFeed) -> Health:
    vehicles_age = age_seconds(live.vehicles_at)
    if live.fetched_at is None:
        return Health(
            status="degraded",
            feed_age_seconds=None,
            vehicles_age_seconds=vehicles_age,
        )
    age = time.monotonic() - live.fetched_at
    status = "ok" if age <= MAX_FEED_AGE_SECONDS else "degraded"
    return Health(
        status=status,
        feed_age_seconds=int(age),
        vehicles_age_seconds=vehicles_age,
    )
