"""A stop's panel, over the page you are on, with its own address."""

from pathlib import Path

from notibondi import main

PLAZA_ITALIA = "6490106165"  # 152A and 505R3
HERE = {"lat": -34.581, "lon": -58.421}


def test_the_panel_has_the_stop_its_star_and_its_arrivals(client):
    html = client.get(f"/partials/stops/{PLAZA_ITALIA}/detail").text

    assert '<h2 id="detail-title" tabindex="-1">PLAZA ITALIA</h2>' in html
    assert f'data-stop-id="{PLAZA_ITALIA}">☆</button>' in html
    assert "<li>152A</li>" in html
    assert f'hx-get="/partials/stops/{PLAZA_ITALIA}/arrivals"' in html
    assert 'class="detail-close"' in html


def test_the_panel_passes_the_walk_to_its_arrivals(client):
    html = client.get(
        f"/partials/stops/{PLAZA_ITALIA}/detail", params={"distance_m": 150}
    ).text

    assert f"/partials/stops/{PLAZA_ITALIA}/arrivals?distance_m=150" in html


def test_the_panel_of_an_unknown_stop_is_404(client):
    assert client.get("/partials/stops/no-existe/detail").status_code == 404


def test_the_stops_own_address_is_the_stops_page_with_the_panel_open(client):
    html = client.get(f"/stops/{PLAZA_ITALIA}").text

    assert '<aside id="detail" class="detail" aria-labelledby="detail-title">' in html
    assert "PLAZA ITALIA</h2>" in html
    # The stops page is under it
    assert '<div id="stops-map" hidden></div>' in html


def test_the_stops_own_address_of_an_unknown_stop_is_404(client):
    assert client.get("/stops/no-existe").status_code == 404


def test_other_pages_have_the_panel_closed_and_empty(client):
    html = client.get("/").text

    assert (
        '<aside id="detail" class="detail" aria-labelledby="detail-title" hidden>'
        in html
    )
    assert 'detail-title" tabindex' not in html


def test_every_stop_in_a_list_links_to_its_panel(client):
    html = client.get("/partials/stops/nearby", params=HERE).text

    assert f'<a class="open-detail" href="/stops/{PLAZA_ITALIA}"' in html
    assert f'data-detail="/partials/stops/{PLAZA_ITALIA}/detail?distance_m=0"' in html


def test_a_favorite_lines_stop_has_no_panel_link(client):
    # It's about the line only, like its missing star
    html = client.get(
        "/partials/lines/favorite", params={"lines": ["505R3:0"], **HERE}
    ).text

    assert "open-detail" not in html


def test_the_panel_has_its_own_history_not_htmxs():
    # htmx's Back puts back a copy of the HTML: a dead map
    js = (Path(main.__file__).parent / "static/ui.js").read_text()

    assert "history.pushState" in js
    assert "popstate" in js


# Opened from a line's map: only that line


def test_the_stops_of_a_line_map_know_their_line(client):
    # route_layers.js passes it to the panel when a stop is tapped
    features = client.get("/api/v1/routes/1001/geojson").json()["features"]
    stops = [f for f in features if f["geometry"]["type"] == "Point"]

    assert {s["properties"]["line"] for s in stops} == {"152A"}


def test_the_panel_of_one_line_shows_only_its_arrivals(client):
    html = client.get(
        f"/partials/stops/{PLAZA_ITALIA}/detail", params={"line": "152A"}
    ).text

    assert f'hx-get="/partials/stops/{PLAZA_ITALIA}/arrivals?line=152A"' in html
    # Its chip says which line the list is of; the others stay plain
    assert '<li class="current">152A</li>' in html
    assert "<li>505R3</li>" in html


def test_the_stops_address_keeps_the_line(client):
    # A reload of /stops/{id}?line=... opens the same panel
    html = client.get(f"/stops/{PLAZA_ITALIA}", params={"line": "152A"}).text

    assert f"/partials/stops/{PLAZA_ITALIA}/arrivals?line=152A" in html


def test_the_panel_without_a_line_has_every_line(client):
    html = client.get(f"/stops/{PLAZA_ITALIA}").text

    assert f'hx-get="/partials/stops/{PLAZA_ITALIA}/arrivals"' in html
    assert 'class="current"' not in html


def test_the_panels_line_must_be_a_line_name(client):
    url = f"/partials/stops/{PLAZA_ITALIA}/detail"

    assert client.get(url, params={"line": "<b>"}).status_code == 422
