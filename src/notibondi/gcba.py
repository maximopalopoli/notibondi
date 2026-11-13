import httpx2
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from notibondi.config import Settings


class GcbaError(Exception):
    """Any failure getting the feed: network, bad status or bad body."""


async def fetch_trip_updates(
    client: httpx2.AsyncClient, settings: Settings
) -> gtfs_realtime_pb2.FeedMessage:
    params = {
        "client_id": settings.gcba_client_id,
        "client_secret": settings.gcba_client_secret.get_secret_value(),
    }
    try:
        resp = await client.get(
            f"{settings.gcba_base_url}/colectivos/tripUpdates", params=params
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
