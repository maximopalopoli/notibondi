"""Favorite stops: the browser keeps the ids, the server finds the nearest."""

from pathlib import Path

import pytest

from notibondi import main
from notibondi.stops import favorite_lines, favorite_stops

PLAZA_ITALIA = "6490106165"
SARMIENTO = "205696"  # ~150 m north of Plaza Italia
EVA_PERON = "691100952"  # ~300 m east
YRIGOYEN = "204229"  # ~2 km south
# Standing on Plaza Italia
HERE = {"lat": -34.581, "lon": -58.421}


def ids_of(stops):
    return [stop.stop_id for stop in stops]


def test_the_nearest_favorite_comes_first(conn):
    stops = favorite_stops(conn, [YRIGOYEN, EVA_PERON, SARMIENTO], **HERE)

    assert ids_of(stops) == [SARMIENTO, EVA_PERON, YRIGOYEN]
    assert stops[0].distance_m == 150
    assert stops[0].lines  # with its lines, like any stop in a list


def test_without_a_position_they_keep_the_users_order(conn):
    stops = favorite_stops(conn, [YRIGOYEN, EVA_PERON, SARMIENTO])

    assert ids_of(stops) == [YRIGOYEN, EVA_PERON, SARMIENTO]
    assert stops[0].distance_m is None


def test_not_by_distance_they_keep_the_users_order_with_their_distance(conn):
    # /favorites: the user orders them, but the distance still shows
    stops = favorite_stops(conn, [YRIGOYEN, SARMIENTO], by_distance=False, **HERE)

    assert ids_of(stops) == [YRIGOYEN, SARMIENTO]
    assert stops[1].distance_m == 150


def test_a_favorite_that_no_longer_exists_is_left_out(conn):
    # A new GTFS may drop a stop the browser still has
    assert ids_of(favorite_stops(conn, ["gone", EVA_PERON])) == [EVA_PERON]


# The partial for the home page


def test_the_partial_shows_only_the_nearest_one(client):
    html = client.get(
        "/partials/stops/favorite", params={"ids": [YRIGOYEN, SARMIENTO], **HERE}
    ).text

    assert html.count('class="stop"') == 1
    assert f'data-stop-id="{SARMIENTO}"' in html
    assert '<span class="distance">150 m</span>' in html
    # Close enough to walk: the arrivals say when to leave
    assert f"/partials/stops/{SARMIENTO}/arrivals?distance_m=150" in html
    assert 'class="note"' not in html


def test_a_far_favorite_shows_km_and_no_walk(client):
    # The arrivals only take a distance you'd walk (up to 1500 m)
    html = client.get(
        "/partials/stops/favorite", params={"ids": [YRIGOYEN], **HERE}
    ).text

    assert '<span class="distance">2,0 km</span>' in html
    assert f'hx-get="/partials/stops/{YRIGOYEN}/arrivals"' in html


def test_without_a_position_it_says_it_is_the_first_one(client):
    html = client.get(
        "/partials/stops/favorite", params={"ids": [YRIGOYEN, SARMIENTO]}
    ).text

    assert f'data-stop-id="{YRIGOYEN}"' in html
    assert "Tu primera favorita: no sabemos dónde estás." in html
    # Only /favorites moves them
    assert "data-move" not in html
    assert 'class="distance"' not in html


def test_when_none_exist_anymore_it_says_so(client):
    html = client.get("/partials/stops/favorite", params={"ids": ["gone"]}).text

    assert "Tus paradas favoritas ya no existen." in html


def test_too_many_ids_are_refused(client):
    ids = [str(i) for i in range(51)]

    assert (
        client.get("/partials/stops/favorite", params={"ids": ids}).status_code == 422
    )


def test_ids_are_required(client):
    assert client.get("/partials/stops/favorite").status_code == 422


# The star in every stop list


def test_every_stop_in_a_list_has_a_star(client):
    html = client.get("/partials/stops/nearby", params=HERE).text

    assert html.count('class="fav"') == html.count('class="stop"') > 0
    assert f'data-stop-id="{SARMIENTO}">☆</button>' in html


def test_every_page_loads_the_favorites_script(client):
    for url in ["/", "/stops", "/routes"]:
        assert "/static/favorites.js" in client.get(url).text


def test_the_home_page_shows_the_favorite(client):
    html = client.get("/").text

    assert '<div id="favorite">' in html
    # home.js uses Favorites: deferred scripts run in order
    assert html.index("/static/favorites.js") < html.index("/static/home.js")


# Favorite lines: a line and a direction, with its stop nearest to you

# Standing on Avenida Sarmiento
AT_SARMIENTO = {"lat": -34.57965, "lon": -58.421}


def test_each_favorite_line_comes_with_its_nearest_stop(conn):
    lines = favorite_lines(conn, [("505R3", 0), ("152A", 1)], **AT_SARMIENTO)

    assert [(f.line, f.headsign) for f in lines] == [
        ("152A", "a La Boca"),  # stops right here
        ("505R3", "a Merlo"),  # its nearest stop is Plaza Italia, 150 m
    ]
    assert lines[0].stop.stop_id == SARMIENTO
    assert lines[0].stop.distance_m == 0
    assert lines[1].stop.stop_id == PLAZA_ITALIA
    assert lines[1].stop.distance_m == 150


def test_without_a_position_lines_have_no_stop_and_keep_the_users_order(conn):
    lines = favorite_lines(conn, [("505R3", 0), ("152A", 1)])

    assert [f.line for f in lines] == ["505R3", "152A"]
    assert all(f.stop is None for f in lines)


def test_a_favorite_line_that_no_longer_exists_is_left_out(conn):
    # Nor a direction it doesn't have: the 505R3 only goes one way
    assert favorite_lines(conn, [("60A", 0), ("505R3", 1)]) == []


def test_the_lines_partial_shows_the_nearest_line_only_with_its_arrivals(client):
    html = client.get(
        "/partials/lines/favorite",
        params={"lines": ["505R3:0", "152A:1"], **AT_SARMIENTO},
    ).text

    assert "<strong>152A</strong> a La Boca" in html
    assert "505R3" not in html
    # Its stop opens with only that line's arrivals
    assert f"/partials/stops/{SARMIENTO}/arrivals?distance_m=0&amp;line=152A" in html
    # The star is the line's: no stop star, no other lines
    assert 'data-line="152A" data-direction="1">☆</button>' in html
    assert "data-stop-id=" in html
    assert 'class="fav" aria-pressed="false" aria-label="Favorita"' not in html
    assert 'class="lines"' not in html


def test_the_lines_partial_with_all_shows_every_line(client):
    html = client.get(
        "/partials/lines/favorite",
        params={"lines": ["505R3:0", "152A:1"], "all": True, **AT_SARMIENTO},
    ).text

    assert html.count('class="favorite-line"') == 2


def test_without_a_position_the_line_says_why_it_has_no_stop(client):
    html = client.get("/partials/lines/favorite", params={"lines": ["152A:1"]}).text

    assert "<strong>152A</strong> a La Boca" in html
    assert "no podemos buscar la parada más cerca" in html
    assert 'class="stop"' not in html


def test_when_no_favorite_line_exists_anymore_it_says_so(client):
    html = client.get("/partials/lines/favorite", params={"lines": ["60A:0"]}).text

    assert "Tus líneas favoritas ya no existen." in html


@pytest.mark.parametrize("bad", ["152A", "152A:2", "1 OR 1:0", "152A:0:1"])
def test_malformed_favorite_lines_are_refused(client, bad):
    response = client.get("/partials/lines/favorite", params={"lines": [bad]})

    assert response.status_code == 422


def test_too_many_favorite_lines_are_refused(client):
    lines = [f"{i}:0" for i in range(51)]

    response = client.get("/partials/lines/favorite", params={"lines": lines})

    assert response.status_code == 422


# All the favorites: the stops with ?all, and the /favorites page


def test_the_stops_partial_with_all_shows_every_stop_in_the_users_order(client):
    html = client.get(
        "/partials/stops/favorite",
        params={"ids": [YRIGOYEN, SARMIENTO], "all": True, **HERE},
    ).text

    assert html.count('class="stop"') == 2
    # Not the nearest first: the user put YRIGOYEN first
    assert html.index(YRIGOYEN) < html.index(SARMIENTO)
    assert html.count('data-move="-1"') == 2
    assert html.count('data-move="1"') == 2
    assert 'class="note"' not in html


def test_all_the_lines_can_be_moved_but_not_their_stops(client):
    html = client.get(
        "/partials/lines/favorite",
        params={"lines": ["505R3:0", "152A:1"], "all": True, **AT_SARMIENTO},
    ).text

    assert html.index("505R3") < html.index("152A")
    # One pair per line: the stop inside each one isn't a favorite to move
    assert html.count('data-move="-1"') == 2


def test_the_favorites_script_adds_new_ones_first_and_moves_them():
    js = (Path(main.__file__).parent / "static/favorites.js").read_text()

    assert "[value, ...values]" in js
    assert "data-move" in js


def test_the_home_page_shows_a_favorite_line_and_links_to_all(client):
    html = client.get("/").text

    assert "<h2>Tu línea favorita</h2>" in html
    assert '<div id="favorite-line">' in html
    assert '<a href="/favorites">Ver todas tus favoritas</a>' in html


def test_the_favorites_page_asks_for_all_of_them(client):
    response = client.get("/favorites")

    assert response.status_code == 200
    assert "<title>Favoritas · notibondi</title>" in response.text
    assert '<div id="favorite" data-all>' in response.text
    assert '<div id="favorite-line" data-all>' in response.text
    assert "/static/home.js" in response.text


# The stars of the lines, on the lines map


def test_each_direction_of_a_branch_has_a_star(client):
    html = client.get("/partials/routes/search", params={"q": "152"}).text

    assert 'data-line="152A" data-direction="0">☆ a Olivos</button>' in html
    assert 'data-line="152A" data-direction="1">☆ a La Boca</button>' in html
