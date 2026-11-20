"""The map on the stops page: what the server gives it to draw."""

import time
from pathlib import Path

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


def bus(vehicle_id, lat=-34.58, lon=-58.42, direction_id=0):
    return Vehicle(
        vehicle_id,
        lat=lat,
        lon=lon,
        timestamp=int(time.time()),
        label=vehicle_id,
        direction_id=direction_id,
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


def test_a_stop_starts_closed_so_it_can_be_opened_and_closed(client):
    # ui.js reads aria-expanded to know whether a tap opens or closes it
    html = client.get("/partials/stops/nearby", params=PLAZA_ITALIA).text

    assert '<button type="button" class="stop" aria-expanded="false"' in html


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


def test_stops_page_has_a_hidden_map_and_its_scripts(client):
    html = client.get("/stops").text

    # Hidden until there are stops: an empty map looks broken
    assert '<div id="stops-map" hidden></div>' in html
    assert "/static/maplibre-gl.js" in html
    assert "/static/stops_map.js" in html


def test_static_serves_the_stops_map_script(client):
    response = client.get("/static/stops_map.js")

    assert response.status_code == 200
    assert "/api/v1/stops/" in response.text


# Only the line you tapped: all of them at once is confusing


def test_stop_vehicles_of_one_line(live_buses):
    response = live_buses.get(
        f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles", params={"line": "505R3"}
    )

    assert response.status_code == 200
    assert response.json()["features"] == []


def test_stop_vehicles_of_one_line_keep_its_unknown_branch_buses(live_buses):
    response = live_buses.get(
        f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles", params={"line": "152A"}
    )

    assert {f["id"] for f in response.json()["features"]} == {"known", "unknown"}


def test_stop_vehicles_of_a_line_that_doesnt_stop_there_is_404(live_buses):
    response = live_buses.get(
        f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles", params={"line": "60A"}
    )

    assert response.status_code == 404


def test_the_lines_of_a_nearby_stop_are_buttons(client):
    html = client.get("/partials/stops/nearby", params=PLAZA_ITALIA).text

    assert (
        '<button type="button" class="line" aria-pressed="false" data-line="152A"'
        in html
    )
    # Not inside the stop's button: a button can't hold other buttons
    stop_button = html[html.index('class="stop"') : html.index("</button>")]
    assert 'class="line"' not in stop_button


def test_the_lines_found_by_name_are_plain_text(client):
    # The name search has no map to draw the buses on
    html = client.get("/partials/stops/search", params={"q": "plaza"}).text

    assert 'class="line"' not in html


def test_opening_a_stop_shows_no_buses_until_a_line_is_tapped():
    js = (Path(main.__file__).parent / "static/stops_map.js").read_text()

    assert "?line=" in js
    assert ".line[data-line]" in js


# GET /api/v1/stops/{stop_id}/lines/{line}/geojson: the path of the tapped line


def test_the_path_of_a_line_is_the_way_it_comes_to_the_stop(client):
    response = client.get(f"/api/v1/stops/{PLAZA_ITALIA_STOP}/lines/152A/geojson")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    features = response.json()["features"]
    assert features
    assert all(f["geometry"]["type"] == "LineString" for f in features)
    # Only the direction(s) that stop here, each once
    directions = [f["properties"]["direction_id"] for f in features]
    assert len(directions) == len(set(directions))


def test_the_path_of_a_line_that_doesnt_stop_there_is_404(client):
    response = client.get(f"/api/v1/stops/{PLAZA_ITALIA_STOP}/lines/60A/geojson")

    assert response.status_code == 404


def test_the_path_of_an_unknown_stop_is_404(client):
    assert client.get("/api/v1/stops/no-existe/lines/152A/geojson").status_code == 404


def test_the_stops_page_loads_the_arrows_before_its_map(client):
    html = client.get("/stops").text

    assert html.index("/static/route_layers.js") < html.index("/static/stops_map.js")


# Only the buses going the way of the stop: the others go away from you.
# Each live route_id is one line in one direction; the ones with arrivals at
# the stop go its way. Not direction_id: it doesn't match the GTFS one.


def two_ways(**routes_by_stop):
    """A 505R3 going each way: route_id 505 comes here, 506 goes the other way."""
    return LiveFeed(
        lines={"505": "505R3", "506": "505R3"},
        unknown_branch={},
        # The same direction_id on both: the filter must not use it
        vehicles={"505": [bus("coming")], "506": [bus("going")]},
        routes_by_stop=routes_by_stop,
    )


def test_stop_vehicles_of_one_line_are_the_ones_coming_here(client):
    live = two_ways(**{PLAZA_ITALIA_STOP: {"505"}})
    app.dependency_overrides[get_live] = lambda: live

    response = client.get(
        f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles", params={"line": "505R3"}
    )

    assert [f["id"] for f in response.json()["features"]] == ["coming"]


def test_a_stop_both_ways_keeps_both(client):
    live = two_ways(**{PLAZA_ITALIA_STOP: {"505", "506"}})
    app.dependency_overrides[get_live] = lambda: live

    response = client.get(
        f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles", params={"line": "505R3"}
    )

    assert {f["id"] for f in response.json()["features"]} == {"coming", "going"}


def test_a_stop_the_feed_doesnt_predict_shows_every_bus_of_the_line(client):
    # Better all of them than a guess
    live = two_ways()
    app.dependency_overrides[get_live] = lambda: live

    response = client.get(
        f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles", params={"line": "505R3"}
    )

    assert {f["id"] for f in response.json()["features"]} == {"coming", "going"}


def test_without_a_line_the_stop_shows_every_bus(client):
    live = two_ways(**{PLAZA_ITALIA_STOP: {"505"}})
    app.dependency_overrides[get_live] = lambda: live

    response = client.get(f"/api/v1/stops/{PLAZA_ITALIA_STOP}/vehicles")

    assert {f["id"] for f in response.json()["features"]} == {"coming", "going"}
