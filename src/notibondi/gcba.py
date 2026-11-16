import httpx2
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from notibondi.config import Settings


class GcbaError(Exception):
    """Any failure getting the feed: network, bad status or bad body."""


# A good download took ~29 s on 2026-11-16, so 30 s was too tight
TRIP_UPDATES_TIMEOUT = 35
# The full feed is ~1.5 MB. Five good downloads on 2026-11-16 took 1.5 to
# 19 s, so 20 s would cut off good ones.
VEHICLE_POSITIONS_TIMEOUT = 30


async def _fetch_feed(
    client: httpx2.AsyncClient,
    settings: Settings,
    path: str,
    timeout: float,
    params: dict[str, str] | None = None,
) -> gtfs_realtime_pb2.FeedMessage:
    all_params = {
        "client_id": settings.gcba_client_id,
        "client_secret": settings.gcba_client_secret.get_secret_value(),
        **(params or {}),
    }

    try:
        resp = await client.get(
            f"{settings.gcba_base_url}{path}", params=all_params, timeout=timeout
        )
    except httpx2.RequestError as e:
        raise GcbaError(f"request failed: {type(e).__name__}") from e

    if resp.status_code != 200:
        raise GcbaError(f"unexpected status {resp.status_code}")

    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(resp.content)
    except DecodeError as e:
        raise GcbaError("response is not a valid protobuf") from e
    return feed


async def fetch_trip_updates(
    client: httpx2.AsyncClient, settings: Settings
) -> gtfs_realtime_pb2.FeedMessage:
    return await _fetch_feed(
        client, settings, "/colectivos/tripUpdates", TRIP_UPDATES_TIMEOUT
    )


async def fetch_vehicle_positions(
    client: httpx2.AsyncClient, settings: Settings
) -> gtfs_realtime_pb2.FeedMessage:
    return await _fetch_feed(
        client, settings, "/colectivos/vehiclePositions", VEHICLE_POSITIONS_TIMEOUT
    )
