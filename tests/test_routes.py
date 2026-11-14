import pytest

from notibondi.routes import route_directions, route_geojson, search_routes

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
