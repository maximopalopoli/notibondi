import pytest

from notibondi.stops import find_nearby_stops

# Plaza Italia, one of the stops of the mini GTFS
PLAZA_ITALIA = {"lat": -34.581, "lon": -58.421}

# Far from every stop of the mini GTFS
NOWHERE = {"lat": -34.7, "lon": -58.6}


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
        "lat": pytest.approx(PLAZA_ITALIA["lat"]),
        "lon": pytest.approx(PLAZA_ITALIA["lon"]),
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


# Validation of GET /api/v1/stops/nearby


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"lat": 91, "lon": -58.421}, "lat"),
        ({"lat": -91, "lon": -58.421}, "lat"),
        ({"lat": -34.581, "lon": 181}, "lon"),
        ({"lat": -34.581, "lon": -181}, "lon"),
        ({**PLAZA_ITALIA, "radius": -5}, "radius"),
        ({**PLAZA_ITALIA, "radius": 0}, "radius"),
        ({**PLAZA_ITALIA, "radius": 1501}, "radius"),
    ],
)
def test_nearby_endpoint_rejects_out_of_range_params(client, params, field):
    response = client.get("/api/v1/stops/nearby", params=params)

    assert response.status_code == 422
    # The error must point at the bad param, not at something else
    assert [e["loc"] for e in response.json()["detail"]] == [["query", field]]


def test_nearby_endpoint_requires_lat_and_lon(client):
    response = client.get("/api/v1/stops/nearby")

    assert response.status_code == 422
    fields = {e["loc"][-1] for e in response.json()["detail"]}
    assert fields == {"lat", "lon"}


def test_nearby_endpoint_accepts_max_radius(client):
    response = client.get(
        "/api/v1/stops/nearby", params={**PLAZA_ITALIA, "radius": 1500}
    )

    assert response.status_code == 200


# GET /partials/stops/nearby


def test_nearby_partial_returns_html(client):
    response = client.get("/partials/stops/nearby", params=PLAZA_ITALIA)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_nearby_partial_is_a_fragment(client):
    # htmx swaps it into #stops, so a whole page would nest <html> in a div
    html = client.get("/partials/stops/nearby", params=PLAZA_ITALIA).text

    assert "<html" not in html
    assert "<head" not in html


def test_nearby_partial_lists_stops_in_order(client):
    html = client.get("/partials/stops/nearby", params=PLAZA_ITALIA).text

    names = ["PLAZA ITALIA", "AVENIDA SARMIENTO 2601", "AVENIDA EVA PERÓN 1249-1299"]
    positions = [html.index(name) for name in names]
    assert positions == sorted(positions)
    assert "AVENIDA HIPÓLITO YRIGOYEN 12036" not in html


def test_nearby_partial_shows_distance_and_lines(client):
    html = client.get("/partials/stops/nearby", params=PLAZA_ITALIA).text

    assert "0 m" in html
    assert "<li>152A</li>" in html
    assert "<li>505R3</li>" in html


def test_nearby_partial_shows_message_when_nothing_is_close(client):
    response = client.get("/partials/stops/nearby", params=NOWHERE)

    assert response.status_code == 200
    assert "No hay paradas cerca." in response.text


def test_nearby_partial_validates_params(client):
    response = client.get("/partials/stops/nearby", params={"lat": 91, "lon": 0})

    assert response.status_code == 422


# Only the stop without lines is within 400 m of this point
NO_LINES_STOP = {"lat": -34.64, "lon": -58.48}


def test_find_nearby_stops_returns_empty_lines_for_stop_without_routes(conn):
    # The LEFT JOIN gives one row with a NULL route, and array_agg would turn
    # it into [None], which list[str] rejects
    stops = find_nearby_stops(conn, radius=400, **NO_LINES_STOP)

    assert [(s.stop_id, s.lines) for s in stops] == [("999001", [])]


def test_nearby_endpoint_returns_empty_lines_for_stop_without_routes(client):
    response = client.get("/api/v1/stops/nearby", params=NO_LINES_STOP)

    assert response.status_code == 200
    assert response.json() == [
        {
            "stop_id": "999001",
            "stop_name": "PARADA SIN LINEAS",
            "distance_m": 0,
            "lat": pytest.approx(NO_LINES_STOP["lat"]),
            "lon": pytest.approx(NO_LINES_STOP["lon"]),
            "lines": [],
        }
    ]


def test_nearby_partial_renders_stop_without_routes(client):
    response = client.get("/partials/stops/nearby", params=NO_LINES_STOP)

    assert response.status_code == 200
    assert "PARADA SIN LINEAS" in response.text
