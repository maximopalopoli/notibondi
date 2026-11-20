import time

import pytest
from sqlalchemy import text

from notibondi.main import app, get_live
from notibondi.realtime import Vehicle
from notibondi.routes import (
    Route,
    get_route,
    route_directions,
    route_geojson,
    search_routes,
)
from notibondi.worker import LiveFeed

# search_routes


def test_search_routes_returns_every_branch_of_a_line(conn):
    routes = search_routes(conn, "152")

    assert [r.route_short_name for r in routes] == ["152A", "152B"]


def test_search_routes_does_not_match_longer_numbers(conn):
    # "15" is line 15, not the start of 152
    routes = search_routes(conn, "15")

    assert [r.route_short_name for r in routes] == ["15A"]


def test_search_routes_ignores_case(conn):
    routes = search_routes(conn, "152a")

    assert [r.route_short_name for r in routes] == ["152A"]


def test_search_routes_matches_names_with_digits_after_letters(conn):
    routes = search_routes(conn, "505")

    assert [r.route_short_name for r in routes] == ["505R3"]


def test_search_routes_returns_id_and_description(conn):
    route = search_routes(conn, "152A")[0]

    assert route.route_id == "1001"
    assert route.route_desc == "La Boca - Olivos"


def test_search_routes_returns_empty_list_when_nothing_matches(conn):
    assert search_routes(conn, "999") == []


# route_directions


def test_route_directions_returns_both_directions_in_order(conn):
    directions = route_directions(conn, "1001")

    assert [d.direction_id for d in directions] == [0, 1]


def test_route_directions_lists_the_stops_in_order(conn):
    outbound, inbound = route_directions(conn, "1001")

    assert [s.stop_id for s in outbound.stops] == ["205696", "6490106165", "204229"]
    assert [s.stop_id for s in inbound.stops] == ["204229", "6490106165", "205696"]


def test_route_directions_uses_headsign_and_shape_of_the_picked_trip(conn):
    outbound, inbound = route_directions(conn, "1001")

    assert (outbound.trip_headsign, outbound.shape_id) == ("a Olivos", "S1")
    assert (inbound.trip_headsign, inbound.shape_id) == ("a La Boca", "S2")


def test_route_directions_returns_stop_name_and_position(conn):
    stop = route_directions(conn, "1001")[0].stops[1]

    assert stop.stop_name == "PLAZA ITALIA"
    assert stop.lat == pytest.approx(-34.581)
    assert stop.lon == pytest.approx(-58.421)


def test_route_directions_returns_one_direction_when_there_is_only_one(conn):
    directions = route_directions(conn, "4167")

    assert [d.direction_id for d in directions] == [0]
    assert [s.stop_id for s in directions[0].stops] == ["6490106165", "691100952"]


def test_route_directions_is_empty_for_a_route_without_trips(conn):
    # 152B is in routes.txt but has no trips
    assert route_directions(conn, "1002") == []


def test_route_directions_is_empty_for_an_unknown_route(conn):
    assert route_directions(conn, "no-existe") == []


# route_geojson


def lines_of(collection):
    return [f for f in collection["features"] if f["geometry"]["type"] == "LineString"]


def points_of(collection):
    return [f for f in collection["features"] if f["geometry"]["type"] == "Point"]


def test_route_geojson_is_a_feature_collection(conn):
    collection = route_geojson(conn, "1001")

    assert collection["type"] == "FeatureCollection"
    assert all(f["type"] == "Feature" for f in collection["features"])


def test_route_geojson_has_one_line_per_direction_and_its_stops(conn):
    collection = route_geojson(conn, "1001")

    assert len(lines_of(collection)) == 2
    assert len(points_of(collection)) == 6


def test_route_geojson_orders_line_points_by_sequence(conn):
    # shapes.txt lists the points of S1 out of order on purpose
    outbound = lines_of(route_geojson(conn, "1001"))[0]

    assert outbound["geometry"]["coordinates"] == [
        [-58.421, -34.57965],
        [-58.421, -34.581],
        [-58.4205, -34.59],
        [-58.421, -34.599],
    ]


def test_route_geojson_puts_longitude_first_in_stops(conn):
    plaza_italia = next(
        p
        for p in points_of(route_geojson(conn, "1001"))
        if p["properties"]["stop_id"] == "6490106165"
    )

    assert plaza_italia["geometry"]["coordinates"] == pytest.approx([-58.421, -34.581])


def test_route_geojson_describes_each_line(conn):
    lines = lines_of(route_geojson(conn, "1001"))

    assert [line["properties"] for line in lines] == [
        {"direction_id": 0, "trip_headsign": "a Olivos"},
        {"direction_id": 1, "trip_headsign": "a La Boca"},
    ]


def test_route_geojson_tags_each_stop_with_its_direction(conn):
    stops = points_of(route_geojson(conn, "1001"))

    assert [
        (p["properties"]["direction_id"], p["properties"]["stop_id"]) for p in stops
    ] == [
        (0, "205696"),
        (0, "6490106165"),
        (0, "204229"),
        (1, "204229"),
        (1, "6490106165"),
        (1, "205696"),
    ]
    assert stops[1]["properties"]["stop_name"] == "PLAZA ITALIA"


def test_route_geojson_keeps_the_stops_when_a_shape_is_missing(conn):
    # The conn fixture rolls back at the end, so this delete doesn't leak
    inbound_shape = route_directions(conn, "1001")[1].shape_id
    conn.execute(
        text("DELETE FROM shapes WHERE shape_id = :shape_id"),
        {"shape_id": inbound_shape},
    )

    collection = route_geojson(conn, "1001")

    assert [line["properties"]["direction_id"] for line in lines_of(collection)] == [0]
    assert len(points_of(collection)) == 6


def test_route_geojson_is_empty_for_a_route_without_trips(conn):
    assert route_geojson(conn, "1002") == {"type": "FeatureCollection", "features": []}


# GET /api/v1/routes/{route_id}/geojson


def test_route_geojson_endpoint_returns_geojson(client):
    response = client.get("/api/v1/routes/1001/geojson")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    assert response.json()["type"] == "FeatureCollection"


def test_route_geojson_endpoint_returns_404_for_unknown_route(client):
    response = client.get("/api/v1/routes/no-existe/geojson")

    assert response.status_code == 404


def test_route_geojson_endpoint_returns_empty_collection_for_route_without_trips(
    client,
):
    response = client.get("/api/v1/routes/1002/geojson")

    assert response.status_code == 200
    assert response.json()["features"] == []


def test_routes_search_is_not_taken_as_a_route_id(client):
    # /routes/search must keep working next to /routes/{route_id}/...
    response = client.get("/api/v1/routes/search", params={"q": "152"})

    assert response.status_code == 200


# GET /api/v1/routes/{route_id}/vehicles


@pytest.fixture
def live_152a(client):
    """The client fixture, but with two fresh 152A buses in the live feed,
    one each way, and a third whose direction the stops don't tell."""
    now = int(time.time())

    def bus(vehicle_id, timestamp=now):
        # The feed's own direction_id, the same on all
        return Vehicle(
            vehicle_id,
            lat=-34.58,
            lon=-58.42,
            timestamp=timestamp,
            label="1",
            direction_id=0,
        )

    live = LiveFeed(
        lines={"311": "152A", "312": "152A", "313": "152A"},
        vehicles={"311": [bus("a")], "312": [bus("b", now - 10)], "313": [bus("c")]},
        directions={"311": 0, "312": 1},
    )
    app.dependency_overrides[get_live] = lambda: live
    return client


def test_route_vehicles_endpoint_returns_the_buses_of_the_line(live_152a):
    response = live_152a.get("/api/v1/routes/1001/vehicles")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    assert sorted(f["id"] for f in response.json()["features"]) == ["a", "b", "c"]


def test_route_vehicles_endpoint_sends_the_direction_for_the_color(live_152a):
    features = live_152a.get("/api/v1/routes/1001/vehicles").json()["features"]

    # The direction the stops give; the feed's own when they don't tell (c)
    directions = {f["id"]: f["properties"]["direction_id"] for f in features}
    assert directions == {"a": 0, "b": 1, "c": 0}


def test_route_vehicles_endpoint_is_empty_for_a_line_without_live_data(live_152a):
    # 15A (route 1003) has no live route in the feed
    response = live_152a.get("/api/v1/routes/1003/vehicles")

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_route_vehicles_endpoint_returns_404_for_unknown_route(client):
    response = client.get("/api/v1/routes/no-existe/vehicles")

    assert response.status_code == 404


# GET /api/v1/routes/search


def test_routes_search_endpoint_returns_json(client):
    response = client.get("/api/v1/routes/search", params={"q": "152"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "route_id": "1001",
            "route_short_name": "152A",
            "route_desc": "La Boca - Olivos",
        },
        {
            "route_id": "1002",
            "route_short_name": "152B",
            "route_desc": "La Boca - Est. Bartolome Mitre",
        },
    ]


def test_routes_search_endpoint_returns_empty_list(client):
    response = client.get("/api/v1/routes/search", params={"q": "999"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("q", ["", ".*", "15|152", "1" * 11])
def test_routes_search_endpoint_rejects_bad_queries(client, q):
    # Only letters and digits get to the regex
    response = client.get("/api/v1/routes/search", params={"q": q})

    assert response.status_code == 422


def test_routes_search_endpoint_requires_q(client):
    response = client.get("/api/v1/routes/search")

    assert response.status_code == 422


# GET /routes and /partials/routes/search


def test_routes_page_has_the_search_input(client):
    response = client.get("/routes")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'hx-get="/partials/routes/search"' in response.text


def test_index_links_to_routes_page(client):
    assert 'href="/routes"' in client.get("/").text


def test_routes_partial_links_each_branch_to_its_page(client):
    response = client.get("/partials/routes/search", params={"q": "152"})

    assert response.status_code == 200
    assert 'href="/routes/1001">152A</a> · La Boca - Olivos' in response.text
    assert 'href="/routes/1002">152B</a>' in response.text


def test_routes_partial_ignores_spaces_around_q(client):
    response = client.get("/partials/routes/search", params={"q": " 15 "})

    assert 'href="/routes/1003">15A</a>' in response.text


def test_routes_partial_says_when_nothing_matches(client):
    response = client.get("/partials/routes/search", params={"q": "999"})

    assert "No se encontraron líneas" in response.text


@pytest.mark.parametrize("q", ["", "   ", ".*", "15|152", "1" * 11])
def test_routes_partial_is_empty_for_bad_queries(client, q):
    # The partial answers 200 with nothing, so htmx just clears the results
    response = client.get("/partials/routes/search", params={"q": q})

    assert response.status_code == 200
    assert response.text == ""


def test_routes_partial_without_q_is_empty(client):
    response = client.get("/partials/routes/search")

    assert response.status_code == 200
    assert response.text == ""


def test_route_pages_are_not_in_api_docs(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/routes" not in paths
    assert "/partials/routes/search" not in paths
    assert "/routes/{route_id}" not in paths


# GET /routes/{route_id}


def test_route_page_shows_name_and_description(client):
    response = client.get("/routes/1001")

    assert response.status_code == 200
    assert "<h1>152A</h1>" in response.text
    assert "La Boca - Olivos" in response.text


def test_route_page_points_the_map_to_the_geojson(client):
    html = client.get("/routes/1001").text

    assert 'data-geojson-url="/api/v1/routes/1001/geojson"' in html


def test_route_page_points_the_map_to_the_vehicles(client):
    html = client.get("/routes/1001").text

    assert 'data-vehicles-url="/api/v1/routes/1001/vehicles"' in html


def test_route_page_has_a_single_map(client):
    # route.js finds the map by id, so a second one would be left empty
    assert client.get("/routes/1001").text.count('id="map"') == 1


def test_route_page_loads_maplibre_before_route_js(client):
    # Both are deferred, so they run in this order
    html = client.get("/routes/1001").text

    assert "/static/maplibre-gl.css" in html
    assert html.index("/static/maplibre-gl.js") < html.index("/static/route.js")
    # route.js uses the RouteLayers it defines
    assert html.index("/static/route_layers.js") < html.index("/static/route.js")


def test_route_page_works_for_a_route_without_trips(client):
    # 152B has no trips: the page loads and the map just stays empty
    response = client.get("/routes/1002")

    assert response.status_code == 200
    assert "<h1>152B</h1>" in response.text


def test_route_page_returns_404_for_unknown_route(client):
    assert client.get("/routes/no-existe").status_code == 404


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/maplibre-gl.js", "javascript"),
        ("/static/maplibre-gl.css", "text/css"),
        ("/static/route.js", "javascript"),
        ("/static/route_layers.js", "javascript"),
    ],
)
def test_static_serves_map_files(client, path, content_type):
    response = client.get(path)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


# get_route


def test_get_route_returns_the_route(conn):
    assert get_route(conn, "1001") == Route(
        route_id="1001", route_short_name="152A", route_desc="La Boca - Olivos"
    )


def test_get_route_returns_none_for_unknown_route(conn):
    assert get_route(conn, "no-existe") is None
