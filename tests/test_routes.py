import pytest

from notibondi.routes import route_directions, search_routes

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
