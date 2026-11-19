"""GET /partials/stops/address: the stops near an address."""

import pytest

from notibondi.geocode import GeocodeError, Place
from notibondi.main import app, get_geocoder

# Near the fixture's Plaza Italia stop (the same point the nearby tests use)
PLAZA_ITALIA = Place(lat=-34.581, lon=-58.421, label="Avenida Santa Fe 4000, Palermo")
# Inside the AMBA but far from every fixture stop
NOWHERE = Place(lat=-34.9, lon=-58.9, label="Ruta 6, Cañuelas")


class FakeGeocoder:
    def __init__(self, answer: Place | None | Exception):
        self.answer = answer
        self.searched: list[str] = []

    async def search(self, q: str) -> Place | None:
        self.searched.append(q)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def client_geocoding(client):
    """The test client with Nominatim's answer fixed by the test."""

    def fix(answer):
        geocoder = FakeGeocoder(answer)
        app.dependency_overrides[get_geocoder] = lambda: geocoder
        return client, geocoder

    return fix


def get(client, q):
    return client.get("/partials/stops/address", params={"q": q})


def test_shows_the_stops_near_the_address(client_geocoding):
    client, geocoder = client_geocoding(PLAZA_ITALIA)

    response = get(client, "Santa Fe 4000")

    assert response.status_code == 200
    assert "<html" not in response.text
    assert (
        "Paradas cerca de <strong>Avenida Santa Fe 4000, Palermo</strong>"
        in response.text
    )
    assert '<button type="button" class="stop"' in response.text
    assert geocoder.searched == ["Santa Fe 4000"]


def test_the_stops_carry_their_distance_so_salí_en_works(client_geocoding):
    # The whole point: an address works like the location, distances included
    client, _ = client_geocoding(PLAZA_ITALIA)

    html = get(client, "Santa Fe 4000").text

    assert "/arrivals?distance_m=" in html
    assert '<span class="distance">' in html


def test_trims_the_address(client_geocoding):
    client, geocoder = client_geocoding(PLAZA_ITALIA)

    get(client, "   Santa Fe 4000  ")

    assert geocoder.searched == ["Santa Fe 4000"]


def test_an_address_not_found_says_so(client_geocoding):
    client, _ = client_geocoding(None)

    response = get(client, "asdfgh")

    assert response.status_code == 200
    assert "No encontramos esa dirección" in response.text
    assert 'class="stop"' not in response.text


def test_an_address_without_stops_nearby_says_so(client_geocoding):
    client, _ = client_geocoding(NOWHERE)

    html = get(client, "Ruta 6").text

    assert "Paradas cerca de <strong>Ruta 6, Cañuelas</strong>" in html
    assert "No hay paradas cerca de esa dirección." in html


def test_nominatim_down_gives_a_message_not_a_crash(client_geocoding):
    client, _ = client_geocoding(GeocodeError("unexpected status 503"))

    response = get(client, "Santa Fe 4000")

    assert response.status_code == 200
    assert "No pudimos buscar la dirección" in response.text


@pytest.mark.parametrize("q", ["", "  ", "ab"])
def test_a_too_short_address_doesnt_ask_nominatim(client_geocoding, q):
    client, geocoder = client_geocoding(PLAZA_ITALIA)

    html = get(client, q).text

    assert "Escribí una dirección" in html
    assert geocoder.searched == []


def test_a_too_long_address_is_rejected(client_geocoding):
    client, geocoder = client_geocoding(PLAZA_ITALIA)

    assert get(client, "x" * 201).status_code == 422
    assert geocoder.searched == []


def test_is_not_in_the_api_docs(client):
    assert "/partials/stops/address" not in client.get("/openapi.json").json()["paths"]
