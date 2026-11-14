import pytest

from notibondi.routes import search_routes

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
