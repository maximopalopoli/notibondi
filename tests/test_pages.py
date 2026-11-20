import pytest
from fastapi.testclient import TestClient

from notibondi.main import app

# Most pages don't touch the database, so they don't need the client fixture.
# The lines page does (its select lists the lines): those tests use with_db.
client = TestClient(app)


@pytest.fixture
def with_db(client):
    return client


# The home page: your favorite stop


def test_index_returns_html_page():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>notibondi</title>" in response.text
    assert '<h1 class="brand">notibondi</h1>' in response.text


def test_index_links_css_and_htmx():
    html = client.get("/").text

    assert "/static/style.css" in html
    assert "/static/htmx.min.js" in html


def test_index_has_no_nearby_stops():
    # They're on /stops: the home page only shows your favorite
    html = client.get("/").text

    assert 'id="stops"' not in html
    assert "/static/location.js" not in html


def test_index_is_not_in_api_docs():
    paths = client.get("/openapi.json").json()["paths"]

    assert "/" not in paths
    assert "/stops" not in paths


# The static files


def test_static_serves_htmx():
    response = client.get("/static/htmx.min.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.text.startswith("var htmx=")


def test_static_serves_css():
    response = client.get("/static/style.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_static_serves_location_script():
    response = client.get("/static/location.js")

    assert response.status_code == 200
    assert "/partials/stops/nearby" in response.text


def test_static_serves_the_ui_script():
    response = client.get("/static/ui.js")

    assert response.status_code == 200
    assert "aria-expanded" in response.text


# The stops page: nearby stops, by location or address


def test_stops_page_has_its_own_title_and_heading():
    response = client.get("/stops")

    assert response.status_code == 200
    assert "<title>Paradas cerca · notibondi</title>" in response.text
    assert "<h1>Paradas cerca</h1>" in response.text
    # The name in the header goes back home
    assert '<a class="brand" href="/">notibondi</a>' in response.text


def test_stops_page_loads_location_script_and_stops_container():
    html = client.get("/stops").text

    assert "/static/location.js" in html
    assert 'id="stops"' in html


def test_stops_page_shows_a_loading_message_before_the_stops_arrive():
    # Without it, the page is blank while the browser asks for the location,
    # and "loading" looks the same as "broken"
    html = client.get("/stops").text

    assert "Buscando paradas cerca tuyo…" in html


def test_stops_page_has_an_address_form_that_searches_on_enter():
    html = client.get("/stops").text

    assert '<form id="address-form"' in html
    assert 'hx-get="/partials/stops/address"' in html
    assert 'hx-target="#stops"' in html
    assert 'id="address" name="q"' in html
    # Nominatim's policy forbids searching while typing: only the form's
    # submit (Enter or the button) may trigger it
    form = html[html.index('<form id="address-form"') : html.index("</form>")]
    assert "hx-trigger" not in form


def test_stops_page_has_search_input_wired_to_the_partial():
    html = client.get("/stops").text

    assert 'id="search"' in html
    assert 'name="q"' in html
    assert 'hx-get="/partials/stops/search"' in html
    assert 'hx-target="#search-results"' in html
    assert 'id="search-results"' in html


# The header and its menu, on every page

PAGES = ["/", "/favorites", "/stops", "/routes"]


def menu_of(html: str) -> str:
    return html[html.index('<details class="menu">') : html.index("</details>")]


def test_every_page_has_the_menu_with_its_links(with_db):
    for url in PAGES:
        html = with_db.get(url).text
        # The current page's link has it; the next test checks it
        menu = menu_of(html).replace(' aria-current="page"', "")

        assert '<summary aria-label="Menú">' in menu
        assert 'href="/">Inicio</a>' in menu
        assert 'href="/favorites">Favoritas</a>' in menu
        assert 'href="/stops">Paradas cerca</a>' in menu
        assert 'href="/routes">Mapa de líneas</a>' in menu
        assert "/static/ui.js" in html


def test_the_menu_marks_the_page_you_are_on(with_db):
    for url in PAGES:
        menu = menu_of(with_db.get(url).text)

        assert menu.count('aria-current="page"') == 1
        assert f'<a href="{url}" aria-current="page">' in menu


def test_the_lines_page_is_called_mapa_de_líneas(with_db):
    html = with_db.get("/routes").text

    assert "<title>Mapa de líneas · notibondi</title>" in html
    assert "<h1>Mapa de líneas</h1>" in html
    assert "Buscar línea" not in html


def test_the_lines_page_has_a_map(with_db):
    html = with_db.get("/routes").text

    assert '<div id="lines-map"></div>' in html
    assert "/static/maplibre-gl.js" in html
    assert "/static/lines_map.js" in html


def test_the_lines_map_starts_at_the_obelisco():
    # Without a location, the map still shows the city, not the middle of the sea
    js = client.get("/static/lines_map.js").text

    assert "-58.3816, -34.6037" in js
