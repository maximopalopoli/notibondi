import pytest

from notibondi.stops import MAX_SEARCH_LIMIT, search_stops

# Stop names of the mini GTFS that contain "AVENIDA", in alphabetical order
AVENIDAS = [
    "AVENIDA EVA PERÓN 1249-1299",
    "AVENIDA HIPÓLITO YRIGOYEN 12036",
    "AVENIDA SARMIENTO 2601",
]


# search_stops


def test_search_stops_ignores_case(conn):
    stops = search_stops(conn, "plaza italia", limit=20)

    assert [s.stop_id for s in stops] == ["6490106165"]


def test_search_stops_matches_part_of_the_name(conn):
    stops = search_stops(conn, "sarmiento", limit=20)

    assert [s.stop_name for s in stops] == ["AVENIDA SARMIENTO 2601"]


def test_search_stops_ignores_case_of_accented_letters(conn):
    stops = search_stops(conn, "perón", limit=20)

    assert [s.stop_name for s in stops] == ["AVENIDA EVA PERÓN 1249-1299"]


def test_search_stops_orders_by_name(conn):
    stops = search_stops(conn, "avenida", limit=20)

    assert [s.stop_name for s in stops] == AVENIDAS


def test_search_stops_respects_limit(conn):
    stops = search_stops(conn, "avenida", limit=2)

    assert [s.stop_name for s in stops] == AVENIDAS[:2]


def test_search_stops_lists_lines_of_each_stop(conn):
    stops = search_stops(conn, "a", limit=20)

    lines = {s.stop_id: s.lines for s in stops}
    assert lines == {
        "6490106165": ["152A", "505R3"],
        "205696": ["152A"],
        "691100952": ["505R3"],
        "204229": ["152A"],
        "999001": [],
    }


def test_search_stops_returns_empty_list_when_nothing_matches(conn):
    assert search_stops(conn, "constitucion", limit=20) == []


@pytest.mark.parametrize("q", ["%%", "A_", "\\"])
def test_search_stops_treats_wildcards_as_plain_text(conn, q):
    # Without escaping, "%%" and "A_" would match almost every stop
    assert search_stops(conn, q, limit=20) == []


# GET /api/v1/stops/search


def test_search_endpoint_returns_matching_stops(client):
    response = client.get("/api/v1/stops/search", params={"q": "plaza italia"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "stop_id": "6490106165",
            "stop_name": "PLAZA ITALIA",
            "lines": ["152A", "505R3"],
        }
    ]


def test_search_endpoint_uses_limit_param(client):
    response = client.get("/api/v1/stops/search", params={"q": "avenida", "limit": 2})

    assert response.status_code == 200
    assert [s["stop_name"] for s in response.json()] == AVENIDAS[:2]


def test_search_endpoint_returns_empty_list_when_nothing_matches(client):
    response = client.get("/api/v1/stops/search", params={"q": "constitucion"})

    assert response.status_code == 200
    assert response.json() == []


# Validation of GET /api/v1/stops/search


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"q": "a"}, "q"),
        ({"q": "x" * 101}, "q"),
        ({"q": "avenida", "limit": 0}, "limit"),
        ({"q": "avenida", "limit": MAX_SEARCH_LIMIT + 1}, "limit"),
    ],
)
def test_search_endpoint_rejects_out_of_range_params(client, params, field):
    response = client.get("/api/v1/stops/search", params=params)

    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["detail"]] == [["query", field]]


def test_search_endpoint_requires_q(client):
    response = client.get("/api/v1/stops/search")

    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["detail"]] == [["query", "q"]]


def test_search_endpoint_accepts_max_limit(client):
    response = client.get(
        "/api/v1/stops/search", params={"q": "avenida", "limit": MAX_SEARCH_LIMIT}
    )

    assert response.status_code == 200
