import pytest

from notibondi.stops import find_nearby_stops

# Plaza Italia, one of the stops of the mini GTFS
PLAZA_ITALIA = {"lat": -34.581, "lon": -58.421}

# Far from every stop of the mini GTFS
NOWHERE = {"lat": -34.7, "lon": -58.6}


@pytest.fixture
def conn(db_engine, gtfs_loaded):
    with db_engine.connect() as conn:
        yield conn


# find_nearby_stops


def test_find_nearby_stops_orders_by_distance(conn):
    stops = find_nearby_stops(conn, radius=400, **PLAZA_ITALIA)

    assert [s.stop_name for s in stops] == [
        "PLAZA ITALIA",
        "AVENIDA SARMIENTO 2601",
        "AVENIDA EVA PERÓN 1249-1299",
    ]


def test_find_nearby_stops_respects_radius(conn):
    stops = find_nearby_stops(conn, radius=200, **PLAZA_ITALIA)

    assert [s.stop_id for s in stops] == ["6490106165", "205696"]


def test_find_nearby_stops_returns_distance_in_meters(conn):
    stops = find_nearby_stops(conn, radius=400, **PLAZA_ITALIA)

    # 0.00135 degrees of latitude is about 150 m
    assert stops[0].distance_m == 0
    assert stops[1].distance_m == pytest.approx(150, abs=5)


def test_find_nearby_stops_lists_lines_of_each_stop(conn):
    stops = find_nearby_stops(conn, radius=400, **PLAZA_ITALIA)

    lines = {s.stop_id: s.lines for s in stops}
    assert lines == {
        "6490106165": ["152A", "505R3"],
        "205696": ["152A"],
        "691100952": ["505R3"],
    }


def test_find_nearby_stops_returns_empty_list_when_nothing_is_close(conn):
    assert find_nearby_stops(conn, radius=400, **NOWHERE) == []


# GET /api/v1/stops/nearby


def test_nearby_endpoint_returns_close_stops(client):
    response = client.get("/api/v1/stops/nearby", params=PLAZA_ITALIA)

    assert response.status_code == 200
    body = response.json()
    assert [s["stop_id"] for s in body] == ["6490106165", "205696", "691100952"]
    assert body[0] == {
        "stop_id": "6490106165",
        "stop_name": "PLAZA ITALIA",
        "distance_m": 0,
        "lines": ["152A", "505R3"],
    }


def test_nearby_endpoint_uses_radius_param(client):
    response = client.get(
        "/api/v1/stops/nearby", params={**PLAZA_ITALIA, "radius": 200}
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_nearby_endpoint_returns_empty_list_when_nothing_is_close(client):
    response = client.get("/api/v1/stops/nearby", params=NOWHERE)

    assert response.status_code == 200
    assert response.json() == []
