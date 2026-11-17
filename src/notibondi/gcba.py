import httpx2
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from notibondi.config import Settings


class GcbaError(Exception):
    """Any failure getting the feed: network, bad status or bad body."""


# A healthy server connects in well under a second. When the GCBA was down
# on 2026-11-16, each try waited 30 s to fail with ConnectTimeout; with a
# short connect timeout it fails in 5 s and the backoff retries sooner.
CONNECT_TIMEOUT = 5
# On 2026-11-17 the feed was 8.9 MB and the server took 23 to 37 s to send
# the first byte, so 35 s cut off good downloads
TRIP_UPDATES_TIMEOUT = httpx2.Timeout(45, connect=CONNECT_TIMEOUT)
# The full feed is ~1.5 MB. Five good downloads on 2026-11-16 took 1.5 to
# 19 s, so 20 s would cut off good ones.
VEHICLE_POSITIONS_TIMEOUT = httpx2.Timeout(30, connect=CONNECT_TIMEOUT)
# The JSON is ~3 MB, but on 2026-11-17 the server took 23 s to send it
ROUTE_NAMES_TIMEOUT = httpx2.Timeout(60, connect=CONNECT_TIMEOUT)


async def _get(
    client: httpx2.AsyncClient,
    settings: Settings,
    path: str,
    timeout: httpx2.Timeout,
    params: dict[str, str] | None = None,
) -> httpx2.Response:
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
    return resp


async def _fetch_feed(
    client: httpx2.AsyncClient,
    settings: Settings,
    path: str,
    timeout: httpx2.Timeout,
) -> gtfs_realtime_pb2.FeedMessage:
    resp = await _get(client, settings, path, timeout)
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


async def fetch_route_names(
    client: httpx2.AsyncClient, settings: Settings
) -> dict[str, str]:
    """The line name of each live route_id with a bus right now: {"834": "152"}.

    From vehiclePositionsSimple, a JSON list of buses. Its positions are not
    used: it has fewer buses than vehiclePositions (8,439 vs 10,274 on
    2026-11-17), but it's the only feed that has the line names.
    """
    resp = await _get(
        client, settings, "/colectivos/vehiclePositionsSimple", ROUTE_NAMES_TIMEOUT
    )
    try:
        return {
            str(bus["route_id"]): bus["route_short_name"]
            for bus in resp.json()
            if bus.get("route_id") and bus.get("route_short_name")
        }
    except (ValueError, TypeError, AttributeError) as e:
        raise GcbaError("response is not a JSON list of buses") from e
