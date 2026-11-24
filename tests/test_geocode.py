import asyncio
from datetime import date, timedelta

import httpx2
import pytest

from notibondi.config import Settings
from notibondi.geocode import (
    AMBA_VIEWBOX,
    CABA_VIEWBOX,
    MAX_CACHED,
    MAX_DAILY_REQUESTS,
    MAX_PENDING,
    GeocodeBusy,
    GeocodeError,
    Geocoder,
    Place,
    normalize,
    short_label,
)

# Trimmed from a real Nominatim jsonv2 answer with addressdetails=1
TRIUNVIRATO = {
    "lat": "-34.5735",
    "lon": "-58.4842",
    "display_name": "3424, Avenida Triunvirato, Villa Urquiza, Buenos Aires, "
    "Comuna 12, Ciudad Autónoma de Buenos Aires, C1431, Argentina",
    "address": {
        "house_number": "3424",
        "road": "Avenida Triunvirato",
        "suburb": "Villa Urquiza",
        "city": "Buenos Aires",
        "state": "Ciudad Autónoma de Buenos Aires",
    },
}
# The same street number in the province, inside the CABA box's corner
ALDO_BONZI = {
    "lat": "-34.705",
    "lon": "-58.52",
    "display_name": "1500, Cárdenas, Aldo Bonzi, La Matanza, Buenos Aires, Argentina",
    "address": {
        "house_number": "1500",
        "road": "Cárdenas",
        "suburb": "Aldo Bonzi",
        "state": "Buenos Aires",
    },
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings():
    return Settings(
        database_url="postgresql+psycopg://unused",
        gcba_client_id="unused",
        gcba_client_secret="unused",
        nominatim_url="https://nominatim.test",
        nominatim_user_agent="notibondi-test/0.1",
    )


class FakeClock:
    """A clock that only moves when the geocoder sleeps (or a test says so)."""

    def __init__(self):
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float):
        self.slept.append(seconds)
        self.now += seconds


def geocoder_with(handler, settings, clock=None) -> Geocoder:
    clock = clock or FakeClock()
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return Geocoder(client, settings, clock=clock, sleep=clock.sleep)


def answering(*results, seen=None):
    def handler(req):
        if seen is not None:
            seen.append(req)
        return httpx2.Response(200, json=list(results))

    return handler


# The request


@pytest.mark.anyio
async def test_asks_nominatim_inside_caba_first(settings):
    seen = []
    await geocoder_with(answering(TRIUNVIRATO, seen=seen), settings).search(
        "Triunvirato 3424"
    )

    url = seen[0].url
    assert url.host == "nominatim.test"
    assert url.path == "/search"
    assert url.params["q"] == "triunvirato 3424"
    assert url.params["format"] == "jsonv2"
    assert url.params["limit"] == "5"
    assert url.params["countrycodes"] == "ar"
    assert url.params["viewbox"] == CABA_VIEWBOX
    # 1, not 0: with 0 the box is only a preference, and "Triunvirato 3424"
    # could land in another city
    assert url.params["bounded"] == "1"
    # Found in CABA: no second request
    assert len(seen) == 1


@pytest.mark.anyio
async def test_not_found_in_caba_asks_the_whole_amba(settings):
    # On 2026-11-19 "Cabildo 2000" in the AMBA box gave Moreno, and
    # "Corrientes 1500" gave Quilmes: CABA first avoids that
    seen = []
    clock = FakeClock()

    def handler(req):
        seen.append(req)
        if req.url.params["viewbox"] == CABA_VIEWBOX:
            return httpx2.Response(200, json=[])
        return httpx2.Response(200, json=[TRIUNVIRATO])

    place = await geocoder_with(handler, settings, clock).search("Maipú 1200")

    assert place is not None
    assert [r.url.params["viewbox"] for r in seen] == [CABA_VIEWBOX, AMBA_VIEWBOX]
    assert seen[1].url.params["limit"] == "1"
    assert all(r.url.params["bounded"] == "1" for r in seen)
    # Two requests in one search still respect the limit
    assert clock.slept == [pytest.approx(1.0)]


@pytest.mark.anyio
async def test_sends_its_own_user_agent(settings):
    # Nominatim's policy blocks the default library User-Agents
    seen = []
    await geocoder_with(answering(TRIUNVIRATO, seen=seen), settings).search("x y")

    assert seen[0].headers["User-Agent"] == "notibondi-test/0.1"


# The answer


@pytest.mark.anyio
async def test_returns_the_place_with_a_short_label(settings):
    place = await geocoder_with(answering(TRIUNVIRATO), settings).search(
        "Triunvirato 3424"
    )

    assert place == Place(
        lat=-34.5735, lon=-58.4842, label="Avenida Triunvirato 3424, Villa Urquiza"
    )


@pytest.mark.anyio
async def test_returns_none_when_nothing_matches(settings):
    assert await geocoder_with(answering(), settings).search("asdfgh") is None


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda req: httpx2.Response(429), "status 429"),
        (lambda req: httpx2.Response(200, text="<html>"), "not a JSON list"),
        (lambda req: httpx2.Response(200, json=[{"lat": "x"}]), "not a JSON list"),
        (lambda req: httpx2.Response(200, json={"error": "x"}), "not a JSON list"),
    ],
)
@pytest.mark.anyio
async def test_a_bad_answer_is_a_geocode_error(settings, handler, reason):
    with pytest.raises(GeocodeError, match=reason):
        await geocoder_with(handler, settings).search("Triunvirato 3424")


@pytest.mark.anyio
async def test_a_network_failure_is_a_geocode_error(settings):
    def handler(req):
        raise httpx2.ConnectTimeout("down", request=req)

    with pytest.raises(GeocodeError, match="ConnectTimeout"):
        await geocoder_with(handler, settings).search("Triunvirato 3424")


def test_short_label_without_a_house_number():
    result = {
        "display_name": "x",
        "address": {"road": "Avenida Cabildo", "suburb": "Belgrano"},
    }

    assert short_label(result) == "Avenida Cabildo, Belgrano"


def test_short_label_outside_caba_uses_the_town():
    result = {
        "display_name": "x",
        "address": {"road": "Maipú", "house_number": "1200", "town": "Vicente López"},
    }

    assert short_label(result) == "Maipú 1200, Vicente López"


def test_short_label_of_a_place_without_a_street():
    result = {"display_name": "Estación Retiro, Retiro, Buenos Aires, Argentina"}

    assert short_label(result) == "Estación Retiro, Retiro"


# The cache: Nominatim asks for it, and the same few addresses repeat


def test_normalize_ignores_case_and_extra_spaces():
    assert normalize("  Triunvirato   3424 ") == normalize("triunvirato 3424")


@pytest.mark.anyio
async def test_the_same_address_asks_only_once(settings):
    seen = []
    geocoder = geocoder_with(answering(TRIUNVIRATO, seen=seen), settings)

    first = await geocoder.search("Triunvirato 3424")
    second = await geocoder.search("  triunvirato  3424")

    assert first == second
    assert len(seen) == 1


@pytest.mark.anyio
async def test_not_found_is_cached_too(settings):
    seen = []
    geocoder = geocoder_with(answering(seen=seen), settings)

    await geocoder.search("asdfgh")
    await geocoder.search("asdfgh")

    # CABA and then the AMBA, once
    assert len(seen) == 2


@pytest.mark.anyio
async def test_a_failure_is_not_cached(settings):
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx2.Response(503)
        return httpx2.Response(200, json=[TRIUNVIRATO])

    geocoder = geocoder_with(handler, settings)
    with pytest.raises(GeocodeError):
        await geocoder.search("Triunvirato 3424")

    assert await geocoder.search("Triunvirato 3424") is not None
    assert len(calls) == 2


@pytest.mark.anyio
async def test_the_cache_forgets_the_oldest_address(settings):
    seen = []
    geocoder = geocoder_with(answering(TRIUNVIRATO, seen=seen), settings)

    for i in range(MAX_CACHED + 1):
        await geocoder.search(f"calle {i}")
    assert len(geocoder.cache) == MAX_CACHED

    await geocoder.search("calle 0")  # forgotten: asks again
    await geocoder.search(f"calle {MAX_CACHED}")  # still there
    assert len(seen) == MAX_CACHED + 2


# The limit: at most 1 request per second


@pytest.mark.anyio
async def test_the_first_request_doesnt_wait(settings):
    clock = FakeClock()
    await geocoder_with(answering(TRIUNVIRATO), settings, clock).search("a b")

    assert clock.slept == []


@pytest.mark.anyio
async def test_a_second_address_right_away_waits_a_second(settings):
    clock = FakeClock()
    geocoder = geocoder_with(answering(TRIUNVIRATO), settings, clock)

    await geocoder.search("a b")
    clock.now += 0.3
    await geocoder.search("c d")

    assert clock.slept == [pytest.approx(0.7)]


@pytest.mark.anyio
async def test_a_second_address_later_doesnt_wait(settings):
    clock = FakeClock()
    geocoder = geocoder_with(answering(TRIUNVIRATO), settings, clock)

    await geocoder.search("a b")
    clock.now += 5
    await geocoder.search("c d")

    assert clock.slept == []


@pytest.mark.anyio
async def test_a_cached_address_doesnt_wait(settings):
    clock = FakeClock()
    geocoder = geocoder_with(answering(TRIUNVIRATO), settings, clock)

    await geocoder.search("a b")
    await geocoder.search("a b")

    assert clock.slept == []


@pytest.mark.anyio
async def test_a_failed_request_counts_toward_the_limit(settings):
    clock = FakeClock()
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx2.Response(503)
        return httpx2.Response(200, json=[TRIUNVIRATO])

    geocoder = geocoder_with(handler, settings, clock)
    with pytest.raises(GeocodeError):
        await geocoder.search("a b")
    await geocoder.search("a b")

    assert clock.slept == [pytest.approx(1.0)]


@pytest.mark.anyio
async def test_two_searches_at_once_still_go_one_second_apart(settings):
    # Two people searching at the same moment: the lock puts one after the other

    clock = FakeClock()
    geocoder = geocoder_with(answering(TRIUNVIRATO), settings, clock)

    await asyncio.gather(geocoder.search("a b"), geocoder.search("c d"))

    assert clock.slept == [pytest.approx(1.0)]


@pytest.mark.anyio
async def test_prefers_a_caba_result_even_if_nominatim_ranks_it_second(settings):
    # What Nominatim did with "corrientes 1500" on 2026-11-19
    seen = []
    place = await geocoder_with(
        answering(ALDO_BONZI, TRIUNVIRATO, seen=seen), settings
    ).search("x y")

    assert place.label == "Avenida Triunvirato 3424, Villa Urquiza"
    assert len(seen) == 1


@pytest.mark.anyio
async def test_a_province_result_inside_the_caba_box_asks_the_amba(settings):
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.params["viewbox"] == CABA_VIEWBOX:
            return httpx2.Response(200, json=[ALDO_BONZI])
        return httpx2.Response(200, json=[TRIUNVIRATO])

    place = await geocoder_with(handler, settings).search("x y")

    assert len(seen) == 2
    assert place.label == "Avenida Triunvirato 3424, Villa Urquiza"


# The line: a flood of new addresses is refused, not queued


def held_until(release: asyncio.Event):
    """A Nominatim that answers only when the test lets it."""

    async def handler(req):
        await release.wait()
        return httpx2.Response(200, json=[TRIUNVIRATO])

    return handler


@pytest.mark.anyio
async def test_too_many_searches_waiting_are_refused(settings):
    release = asyncio.Event()
    geocoder = geocoder_with(held_until(release), settings)
    waiting = [
        asyncio.create_task(geocoder.search(f"calle {i}")) for i in range(MAX_PENDING)
    ]
    await asyncio.sleep(0)  # all of them in line

    with pytest.raises(GeocodeBusy):
        await geocoder.search("one more")

    release.set()
    await asyncio.gather(*waiting)
    # Once the line empties, new searches go through again
    assert await geocoder.search("later") is not None


@pytest.mark.anyio
async def test_a_cached_address_answers_even_with_a_full_line(settings):
    release = asyncio.Event()
    release.set()
    geocoder = geocoder_with(held_until(release), settings)
    await geocoder.search("Triunvirato 3424")
    release.clear()
    waiting = [
        asyncio.create_task(geocoder.search(f"calle {i}")) for i in range(MAX_PENDING)
    ]
    await asyncio.sleep(0)

    assert await geocoder.search("Triunvirato 3424") is not None

    release.set()
    await asyncio.gather(*waiting)


@pytest.mark.anyio
async def test_a_failed_search_leaves_the_line(settings):
    geocoder = geocoder_with(lambda req: httpx2.Response(503), settings)
    for i in range(MAX_PENDING + 1):
        with pytest.raises(GeocodeError) as error:
            await geocoder.search(f"calle {i}")
        assert not isinstance(error.value, GeocodeBusy)

    assert geocoder.pending == 0


# The daily budget: a bot can't keep Nominatim busy all day


@pytest.mark.anyio
async def test_past_the_daily_requests_address_search_waits_for_tomorrow(
    settings, monkeypatch
):
    monkeypatch.setattr("notibondi.geocode.MAX_DAILY_REQUESTS", 2)
    day = [date(2026, 11, 24)]
    clock = FakeClock()
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(answering(TRIUNVIRATO)))
    geocoder = Geocoder(
        client, settings, clock=clock, sleep=clock.sleep, today=lambda: day[0]
    )
    await geocoder.search("calle 1")
    await geocoder.search("calle 2")

    with pytest.raises(GeocodeBusy):
        await geocoder.search("calle 3")
    # What's cached still answers
    assert await geocoder.search("calle 1") is not None

    day[0] += timedelta(days=1)
    assert await geocoder.search("calle 3") is not None


def test_the_daily_budget_leaves_room_for_real_use():
    # One search is 1 or 2 calls: a thousand searches a day still fit
    assert 1000 <= MAX_DAILY_REQUESTS < 86_400
