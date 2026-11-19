from fastapi.testclient import TestClient

from notibondi.main import app

# The pages don't touch the database, so they don't need the client fixture
client = TestClient(app)


def test_index_returns_html_page():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>notibondi</title>" in response.text
    assert "<h1>notibondi</h1>" in response.text


def test_index_links_css_and_htmx():
    html = client.get("/").text

    assert "/static/style.css" in html
    assert "/static/htmx.min.js" in html


def test_static_serves_htmx():
    response = client.get("/static/htmx.min.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.text.startswith("var htmx=")


def test_static_serves_css():
    response = client.get("/static/style.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_index_is_not_in_api_docs():
    paths = client.get("/openapi.json").json()["paths"]

    assert "/" not in paths


def test_index_loads_location_script_and_stops_container():
    html = client.get("/").text

    assert "/static/location.js" in html
    assert 'id="stops"' in html


def test_static_serves_location_script():
    response = client.get("/static/location.js")

    assert response.status_code == 200
    assert "/partials/stops/nearby" in response.text


def test_index_shows_a_loading_message_before_the_stops_arrive():
    # Without it, the page is blank while the browser asks for the location,
    # and "loading" looks the same as "broken"
    html = client.get("/").text

    assert "Buscando paradas cerca tuyo…" in html


def test_index_has_an_address_form_that_searches_on_enter():
    html = client.get("/").text

    assert '<form id="address-form"' in html
    assert 'hx-get="/partials/stops/address"' in html
    assert 'hx-target="#stops"' in html
    assert 'id="address" name="q"' in html
    # Nominatim's policy forbids searching while typing: only the form's
    # submit (Enter or the button) may trigger it
    form = html[html.index('<form id="address-form"') : html.index("</form>")]
    assert "hx-trigger" not in form


def test_index_has_search_input_wired_to_the_partial():
    html = client.get("/").text

    assert 'id="search"' in html
    assert 'name="q"' in html
    assert 'hx-get="/partials/stops/search"' in html
    assert 'hx-target="#search-results"' in html
    assert 'id="search-results"' in html
