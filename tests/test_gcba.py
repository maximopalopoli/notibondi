from pathlib import Path

import httpx2
import pytest

from notibondi.config import Settings
from notibondi.gcba import (
    GcbaError,
    fetch_route_names,
    fetch_trip_updates,
    fetch_vehicle_positions,
)

FEED = Path(__file__).parent / "fixtures" / "trip_updates_205.pb"


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


def client_with(handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


@pytest.mark.anyio
async def test_returns_the_parsed_feed_on_200(settings):
    async with client_with(
        lambda req: httpx2.Response(200, content=FEED.read_bytes())
    ) as c:
        feed = await fetch_trip_updates(c, settings)

    assert len(feed.entity) > 0
    assert feed.entity[0].HasField("trip_update")


@pytest.mark.anyio
async def test_sends_the_credentials_to_the_trip_updates_url(settings):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx2.Response(200, content=FEED.read_bytes())

    async with client_with(handler) as c:
        await fetch_trip_updates(c, settings)

    url = seen[0].url
    assert url.host == "gcba.test"
    assert url.path == "/colectivos/tripUpdates"
    assert url.params["client_id"] == "the-id"
    assert url.params["client_secret"] == "the-secret"


@pytest.mark.anyio
async def test_vehicle_positions_uses_its_own_url_and_the_credentials(settings):
    seen = []

    def handler(req):
        seen.append(req)
        body = (FEED.parent / "vehicle_positions_205.pb").read_bytes()
        return httpx2.Response(200, content=body)

    async with client_with(handler) as c:
        feed = await fetch_vehicle_positions(c, settings)

    url = seen[0].url
    assert url.path == "/colectivos/vehiclePositions"
    assert url.params["client_id"] == "the-id"
    assert url.params["client_secret"] == "the-secret"
    assert feed.entity[0].HasField("vehicle")


@pytest.mark.anyio
async def test_a_timeout_is_a_gcba_error(settings):
    def handler(req):
        raise httpx2.ReadTimeout("too slow", request=req)

    async with client_with(handler) as c:
        with pytest.raises(GcbaError, match="ReadTimeout"):
            await fetch_vehicle_positions(c, settings)


@pytest.mark.parametrize(
    ("fetch", "read_timeout"),
    [(fetch_trip_updates, 45), (fetch_vehicle_positions, 30)],
)
@pytest.mark.anyio
async def test_connects_fast_but_reads_slow(settings, fetch, read_timeout):
    seen = []

    def handler(req):
        seen.append(req)
        # any valid feed works: this test only looks at the request
        return httpx2.Response(200, content=FEED.read_bytes())

    async with client_with(handler) as c:
        await fetch(c, settings)

    timeout = seen[0].extensions["timeout"]
    assert timeout["connect"] == 5
    assert timeout["read"] == read_timeout


@pytest.mark.anyio
async def test_raises_gcba_error_on_500(settings):
    async with client_with(lambda req: httpx2.Response(500)) as c:
        with pytest.raises(GcbaError, match="500"):
            await fetch_trip_updates(c, settings)


@pytest.mark.anyio
async def test_raises_gcba_error_when_the_request_fails(settings):
    def handler(req):
        raise httpx2.ConnectTimeout("timed out", request=req)

    async with client_with(handler) as c:
        with pytest.raises(GcbaError, match="ConnectTimeout"):
            await fetch_trip_updates(c, settings)


@pytest.mark.anyio
async def test_raises_gcba_error_when_the_body_is_not_protobuf(settings):
    html = b"<html><body>Service Unavailable</body></html>"
    async with client_with(lambda req: httpx2.Response(200, content=html)) as c:
        with pytest.raises(GcbaError, match="protobuf"):
            await fetch_trip_updates(c, settings)


@pytest.mark.anyio
async def test_error_messages_never_include_the_secret(settings):
    async with client_with(lambda req: httpx2.Response(500)) as c:
        with pytest.raises(GcbaError) as exc:
            await fetch_trip_updates(c, settings)

    assert "the-secret" not in str(exc.value)


# fetch_route_names

# Two buses as they come in vehiclePositionsSimple (2026-11-17), fewer fields
SIMPLE_BUSES = [
    {"route_id": "835", "route_short_name": "152", "id": "1937", "direction": 1},
    {"route_id": "1553", "route_short_name": "228B", "id": "2164", "direction": 0},
]


@pytest.mark.anyio
async def test_route_names_maps_each_route_id_to_its_name(settings):
    async with client_with(lambda req: httpx2.Response(200, json=SIMPLE_BUSES)) as c:
        names = await fetch_route_names(c, settings)

    assert names == {"835": "152", "1553": "228B"}


@pytest.mark.anyio
async def test_route_names_uses_the_simple_feed_with_a_long_read(settings):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx2.Response(200, json=SIMPLE_BUSES)

    async with client_with(handler) as c:
        await fetch_route_names(c, settings)

    url = seen[0].url
    assert url.path == "/colectivos/vehiclePositionsSimple"
    assert url.params["client_secret"] == "the-secret"
    assert seen[0].extensions["timeout"]["connect"] == 5
    assert seen[0].extensions["timeout"]["read"] == 60


@pytest.mark.anyio
async def test_route_names_skips_buses_without_a_route_or_a_name(settings):
    buses = [
        *SIMPLE_BUSES,
        {"route_id": "", "route_short_name": "60"},
        {"route_id": "999", "route_short_name": None},
        {"id": "1"},
    ]
    async with client_with(lambda req: httpx2.Response(200, json=buses)) as c:
        names = await fetch_route_names(c, settings)

    assert names == {"835": "152", "1553": "228B"}


@pytest.mark.anyio
async def test_route_names_reads_a_numeric_route_id_as_text(settings):
    buses = [{"route_id": 835, "route_short_name": "152"}]
    async with client_with(lambda req: httpx2.Response(200, json=buses)) as c:
        assert await fetch_route_names(c, settings) == {"835": "152"}


@pytest.mark.parametrize(
    "body",
    [b"<html>Service Unavailable</html>", b'{"error": "x"}', b"[1, 2]"],
)
@pytest.mark.anyio
async def test_route_names_raises_gcba_error_on_a_bad_body(settings, body):
    async with client_with(lambda req: httpx2.Response(200, content=body)) as c:
        with pytest.raises(GcbaError, match="JSON"):
            await fetch_route_names(c, settings)


@pytest.mark.anyio
async def test_route_names_raises_gcba_error_on_500(settings):
    async with client_with(lambda req: httpx2.Response(500)) as c:
        with pytest.raises(GcbaError, match="500"):
            await fetch_route_names(c, settings)
