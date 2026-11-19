"""The map on the home page: what the server gives it to draw."""

import time

import pytest

from notibondi import main
from notibondi.geocode import Place
from notibondi.main import app, get_geocoder, get_live
from notibondi.realtime import Vehicle
from notibondi.stops import find_nearby_stops, stop_lines
from notibondi.worker import LiveFeed

PLAZA_ITALIA = {"lat": -34.581, "lon": -58.421}
PLAZA_ITALIA_STOP = "6490106165"  # 152A and 505R3
ONLY_505R3_STOP = "691100952"
SANTA_FE = Place(lat=-34.5812, lon=-58.4213, label="Avenida Santa Fe 4000, Palermo")


class FoundGeocoder:
    async def search(self, q: str) -> Place:
        return SANTA_FE


def bus(vehicle_id, lat=-34.58, lon=-58.42):
    return Vehicle(
        vehicle_id,
        lat=lat,
        lon=lon,
        timestamp=int(time.time()),
        label=vehicle_id,
        direction_id=0,
    )


@pytest.fixture
def live_buses(client):
    """A 152A bus, and a 152 one of unknown branch, in the live feed."""
    live = LiveFeed(
        lines={"311": "152A"},
        unknown_branch={"999": "152"},
        vehicles={"311": [bus("known")], "999": [bus("unknown")]},
    )
    app.dependency_overrides[get_live] = lambda: live
    return client


# The stops carry their position


def test_nearby_stops_have_their_coordinates(conn):
    stops = find_nearby_stops(conn, radius=400, **PLAZA_ITALIA)

    # Plaza Italia is the stop right at the point
    assert stops[0].lat == pytest.approx(PLAZA_ITALIA["lat"])
    assert stops[0].lon == pytest.approx(PLAZA_ITALIA["lon"])


def test_the_nearby_list_says_where_it_measures_from(client):
    html = client.get("/partials/stops/nearby", params=PLAZA_ITALIA).text

    assert 'data-origin-lat="-34.581" data-origin-lon="-58.421"' in html
    assert f'<li data-stop-id="{PLAZA_ITALIA_STOP}" data-lat="' in html


def test_the_address_list_measures_from_the_address(client):
    app.dependency_overrides[get_geocoder] = FoundGeocoder

    html = client.get("/partials/stops/address", params={"q": "Santa Fe 4000"}).text

    assert 'data-origin-lat="-34.5812" data-origin-lon="-58.4213"' in html


def test_the_name_search_has_nothing_for_the_map(client):
    # Its results go under the search box, not to the map
    html = client.get("/partials/stops/search", params={"q": "plaza"}).text

    assert "data-origin-lat" not in html
    assert "data-lat" not in html


# The lines of a stop


def test_stop_lines(conn):
    assert stop_lines(conn, PLAZA_ITALIA_STOP) == ["152A", "505R3"]


def test_stop_lines_of_an_unknown_stop_is_none(conn):
    assert stop_lines(conn, "no-existe") is None


# GET /api/v1/stops/{stop_id}/vehicles


def test_stop_vehicles_are_the_buses_of_its_lines(live_buses):
    response = live_buses.get(f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    lines = {
        f["id"]: (f["properties"]["line"], f["properties"]["branch_known"])
        for f in response.json()["features"]
    }
    # The unknown branch one says "152", not a guessed "152A"
    assert lines == {"known": ("152A", True), "unknown": ("152", False)}


def test_stop_vehicles_skip_the_other_lines(live_buses):
    response = live_buses.get(f"/api/v1/stops/{ONLY_505R3_STOP}/vehicles")

    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_a_bus_of_unknown_branch_comes_only_once(client, monkeypatch):
    # 152A and 152B both stop here: the 152 bus matches both
    live = LiveFeed(
        lines={"311": "152A"},
        unknown_branch={"999": "152"},
        vehicles={"999": [bus("unknown")]},
    )
    app.dependency_overrides[get_live] = lambda: live
    monkeypatch.setattr(main, "stop_lines", lambda conn, stop_id: ["152A", "152B"])

    response = client.get(f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles")
    features = response.json()["features"]

    assert [f["id"] for f in features] == ["unknown"]


def test_stop_vehicles_of_an_unknown_stop_is_404(client):
    assert client.get("/api/v1/stops/no-existe/vehicles").status_code == 404


# The page


def test_index_has_a_hidden_map_and_its_scripts(client):
    html = client.get("/").text

    # Hidden until there are stops: an empty map looks broken
    assert '<div id="home-map" hidden></div>' in html
    assert "/static/maplibre-gl.js" in html
    assert "/static/home.js" in html


def test_static_serves_the_home_map_script(client):
    response = client.get("/static/home.js")

    assert response.status_code == 200
    assert "/api/v1/stops/" in response.text
